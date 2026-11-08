"""Deterministic BM25 retrieval and outline generation for the Two-Mode Terminal Query Engine.

Spec Sections 4.2 and 4.4. Pure Python; no extra dependencies.
"""
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from intentflow.models import QueryPlan, SourceRequest
from app.config import settings
from app.copilot.services.token_service import estimate_tokens
from .store import IntentStore, safe_repo_path


def tokenize(text: str) -> List[str]:
    """Extract lowercased alphanumeric tokens."""
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 1]


class BM25Index:
    """Standard Okapi BM25 implementation."""

    def __init__(self, corpus: Dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.doc_ids = list(corpus.keys())
        self.k1 = k1
        self.b = b
        self.docs_tokens: Dict[str, List[str]] = {
            doc_id: tokenize(text) for doc_id, text in corpus.items()
        }
        self.n_docs = len(self.doc_ids)
        if self.n_docs > 0:
            self.avg_len = sum(len(toks) for toks in self.docs_tokens.values()) / self.n_docs
        else:
            self.avg_len = 1.0

        # Document frequency per token
        self.df: Dict[str, int] = {}
        for toks in self.docs_tokens.values():
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1

    def idf(self, token: str) -> float:
        df = self.df.get(token, 0)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: List[str], doc_id: str) -> float:
        toks = self.docs_tokens.get(doc_id, [])
        if not toks:
            return 0.0
        doc_len = len(toks)
        tf_map: Dict[str, int] = {}
        for t in toks:
            tf_map[t] = tf_map.get(t, 0) + 1

        score = 0.0
        denom_norm = self.k1 * (1.0 - self.b + self.b * (doc_len / max(1.0, self.avg_len)))
        for q in query_tokens:
            tf = tf_map.get(q, 0)
            if tf > 0:
                idf = self.idf(q)
                score += idf * ((tf * (self.k1 + 1.0)) / (tf + denom_norm))
        return score

    def rank(self, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        q_tokens = tokenize(query)
        if not q_tokens or not self.doc_ids:
            return [(doc_id, 0.0) for doc_id in self.doc_ids[:top_k]]
        scored = [(doc_id, self.score(q_tokens, doc_id)) for doc_id in self.doc_ids]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ------------------------------------------------------------------ BM25 Plan Generation


def build_bm25_plan(
    store: IntentStore,
    question: str,
    selected_tenet_id: Optional[str] = None,
    max_files: Optional[int] = None,
) -> QueryPlan:
    """Build a deterministic fallback plan using BM25 over annotations and tenets."""
    limit_files = max_files or settings.query_planner_max_files
    tenets = store.tenets()
    all_claims = store.all_claims()

    # 1. Corpus for files from annotations
    annotated_paths = store.annotated_paths()
    file_corpus: Dict[str, str] = {}
    for p in annotated_paths:
        ann = store.get_annotation(p) or {}
        purpose = ann.get("purpose", "")
        resps = " ".join(ann.get("responsibilities", []))
        invs = " ".join(ann.get("invariants", []))
        file_corpus[p] = f"{p} {purpose} {resps} {invs}"

    file_index = BM25Index(file_corpus)
    ranked_files = file_index.rank(question, top_k=limit_files)
    planned_files = [p for p, sc in ranked_files if sc > 0][:limit_files]

    # If nothing scored > 0, include top 2 files if available
    if not planned_files and file_corpus:
        planned_files = [p for p, _ in ranked_files[: min(2, len(ranked_files))]]

    # 2. Corpus for tenets
    tenet_corpus: Dict[str, str] = {}
    for tid, t in tenets.items():
        name = t.get("name", "") if isinstance(t, dict) else getattr(t, "name", "")
        fn = t.get("functionality", "") if isinstance(t, dict) else getattr(t, "functionality", "")
        t_claims = [
            (c.statement if hasattr(c, "statement") else c.get("statement", ""))
            for c in all_claims
            if (getattr(c, "tenet_id", None) or (c.get("tenet_id") if isinstance(c, dict) else None)) == tid
        ]
        tenet_corpus[tid] = f"{name} {fn} {' '.join(t_claims)}"

    tenet_index = BM25Index(tenet_corpus)
    ranked_tenets = tenet_index.rank(question, top_k=4)
    planned_tenets = [tid for tid, sc in ranked_tenets if sc > 0][:4]

    if selected_tenet_id and selected_tenet_id in tenets and selected_tenet_id not in planned_tenets:
        planned_tenets = [selected_tenet_id] + planned_tenets[:3]

    # 3. Claims for planned tenets
    planned_claims: List[str] = []
    for c in all_claims:
        c_tid = getattr(c, "tenet_id", None) or (c.get("tenet_id") if isinstance(c, dict) else None)
        c_id = getattr(c, "id", None) or (c.get("id") if isinstance(c, dict) else None)
        if c_tid in planned_tenets and c_id:
            planned_claims.append(c_id)
            if len(planned_claims) >= 10:
                break

    keywords = [t for t in tokenize(question) if len(t) > 2][:8]

    return QueryPlan(
        question_type="explain",
        files=planned_files,
        tenets=planned_tenets,
        claims=planned_claims,
        needs_source=False,
        source_requests=[],
        keywords=keywords,
        rounds=1,
        fallback_used=True,
    )


# ------------------------------------------------------------------ Outline Cache & Builder

_OUTLINE_CACHE: Dict[str, Tuple[float, str, bool]] = {}


def invalidate_outline_cache(workspace_id: int) -> None:
    for k in list(_OUTLINE_CACHE.keys()):
        if k.startswith(f"{workspace_id}:"):
            _OUTLINE_CACHE.pop(k, None)


def _get_max_annotation_mtime(store: IntentStore) -> float:
    base = store._path("annotations")
    if not base.exists():
        return 0.0
    mtimes = [f.stat().st_mtime for f in base.rglob("*.json") if f.is_file()]
    return max(mtimes) if mtimes else 0.0


def _count_loc(p: Path) -> int:
    try:
        return len(p.read_text(errors="ignore").splitlines())
    except Exception:
        return 0


def _detect_lang(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".json": "json",
        ".md": "markdown",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
        ".sh": "bash",
    }.get(ext, ext.lstrip(".") or "txt")


def build_outline(
    store: IntentStore,
    repo_dir: Path,
    question: str = "",
    selected_tenet_id: Optional[str] = None,
    budget: Optional[int] = None,
) -> Tuple[str, bool]:
    """Returns (outline_text, zero_annotations: bool).

    Budget defaults to QUERY_OUTLINE_TOKEN_BUDGET.
    Lines format: path | lang | LOC | purpose (<=100 chars, from annotation, or "(unannotated)")
    """
    token_budget = budget or settings.query_outline_token_budget
    last_sha = getattr(store, "last_synced_sha", "nosha")
    max_mtime = _get_max_annotation_mtime(store)
    cache_key = f"{store.wid}:{last_sha}:{max_mtime}:{question[:30]}:{selected_tenet_id}"

    if cache_key in _OUTLINE_CACHE:
        cached_time, cached_outline, cached_zero = _OUTLINE_CACHE[cache_key]
        if cached_time >= max_mtime:
            return cached_outline, cached_zero

    annotated_paths = store.annotated_paths()
    zero_annotations = len(annotated_paths) == 0

    # Discover files from repo_dir or imports or annotations
    files: List[str] = []
    if repo_dir.exists():
        for f in sorted(repo_dir.rglob("*")):
            if f.is_file() and not any(part.startswith(".") or part in ("node_modules", "dist", "build", "__pycache__") for part in f.parts):
                rel = str(f.relative_to(repo_dir)).replace("\\", "/")
                files.append(rel)
    if not files:
        imports_data = store.imports() or {}
        files = sorted(list({f["path"] for f in imports_data.get("files", [])}))
    if not files:
        files = sorted(list(annotated_paths))

    # Identify files linked to selected tenet
    selected_files: Set[str] = set()
    if selected_tenet_id:
        tenet = store.tenets().get(selected_tenet_id)
        if tenet:
            for l in tenet.get("code_links", []):
                p = l.get("path") or l.get("file")
                if p:
                    selected_files.add(p)

    # Rank directories / files by BM25 relevance to question
    annot_corpus: Dict[str, str] = {}
    for p in files:
        ann = store.get_annotation(p) or {}
        purpose = ann.get("purpose", "")
        annot_corpus[p] = f"{p} {purpose}"

    bm25 = BM25Index(annot_corpus)
    ranked = bm25.rank(question, top_k=len(files))
    top_matches: Set[str] = {p for p, sc in ranked[:6] if sc > 0}

    # Group files by directory
    dir_groups: Dict[str, List[str]] = {}
    for p in files:
        d = os.path.dirname(p) or "."
        dir_groups.setdefault(d, []).append(p)

    def render(collapsed_dirs: Set[str]) -> str:
        lines: List[str] = []
        for d in sorted(dir_groups.keys()):
            file_list = dir_groups[d]
            if d in collapsed_dirs:
                topics: List[str] = []
                for p in file_list:
                    ann = store.get_annotation(p) or {}
                    purp = ann.get("purpose", "")
                    if purp:
                        topics.append(purp[:30])
                top_str = f", topics: {'; '.join(topics[:3])}" if topics else ""
                lines.append(f"{d}/ ({len(file_list)} files{top_str})")
            else:
                for p in file_list:
                    ann = store.get_annotation(p) or {}
                    purp = ann.get("purpose")
                    if purp:
                        purp_str = purp[:100].replace("\n", " ")
                    else:
                        purp_str = "(unannotated)"
                    loc = _count_loc(repo_dir / p) if repo_dir.exists() and (repo_dir / p).exists() else 0
                    lang = _detect_lang(p)
                    lines.append(f"{p} | {lang} | {loc} LOC | {purp_str}")
        return "\n".join(lines)

    # Start with all expanded
    collapsed: Set[str] = set()
    text = render(collapsed)
    tokens = estimate_tokens(text)

    # If over budget: collapse directories with lowest BM25 relevance
    if tokens > token_budget:
        # Score each directory
        dir_scores: List[Tuple[str, float]] = []
        for d, f_list in dir_groups.items():
            # Don't collapse if contains selected_files or top_matches
            has_must_keep = any(f in selected_files or f in top_matches for f in f_list)
            if has_must_keep:
                score = float("inf")
            else:
                score = sum(bm25.score(tokenize(question), f) for f in f_list)
            dir_scores.append((d, score))

        dir_scores.sort(key=lambda x: x[1])  # lowest score first
        for d, sc in dir_scores:
            if sc == float("inf"):
                continue
            collapsed.add(d)
            text = render(collapsed)
            if estimate_tokens(text) <= token_budget:
                break

    _OUTLINE_CACHE[cache_key] = (max_mtime, text, zero_annotations)
    return text, zero_annotations
