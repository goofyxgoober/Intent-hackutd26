"""Codebase annotation engine (no AST engine): two-pass annotation, chunk hashing, staleness, import edges."""
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from pydantic import BaseModel, Field

from .llm import Nemotron, log_usage
from .models import Actor
from .store import Store


class WholeFileSummary(BaseModel):
    purpose: str = Field(description="Primary purpose and high-level role of this file")
    responsibilities: List[str] = Field(default_factory=list, description="Core responsibilities")
    dependencies: List[str] = Field(default_factory=list, description="Key imported dependencies or callers")
    sections: List[str] = Field(default_factory=list, description="Rough structural sections")


class ChunkComment(BaseModel):
    chunk_hash: str
    start_line: int
    end_line: int
    comment: str
    uncertain: bool = False


class FileAnnotations(BaseModel):
    path: str
    file_hash: str
    summary: WholeFileSummary
    chunks: List[ChunkComment] = Field(default_factory=list)


def normalize_chunk(text: str) -> str:
    """Normalize whitespace and blank lines before hashing (spec 9)."""
    lines = [line.rstrip() for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    return "\n".join(non_empty).strip()


def compute_chunk_hash(text: str) -> str:
    norm = normalize_chunk(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def extract_import_edges(repo_dir: Path) -> List[Tuple[str, str]]:
    """Pattern matching for import edges without AST engine (Python & TypeScript) (spec 9)."""
    edges: List[Tuple[str, str]] = []
    supported_exts = {".py", ".ts", ".tsx", ".js", ".jsx"}

    all_files = {}
    for p in repo_dir.rglob("*"):
        if p.is_file() and p.suffix in supported_exts and not any(part.startswith(".") for part in p.parts):
            rel = str(p.relative_to(repo_dir))
            all_files[rel] = p

    # Python regex
    py_from_import = re.compile(r"^\s*from\s+([a-zA-Z0-9_.]+)\s+import", re.MULTILINE)
    py_import = re.compile(r"^\s*import\s+([a-zA-Z0-9_.]+)", re.MULTILINE)

    # TS regex
    ts_import = re.compile(r'''(?:import|require)\s*\(?['"]([.@/a-zA-Z0-9_-]+)['"]\)?''')

    for rel_path, file_path in all_files.items():
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if rel_path.endswith(".py"):
            for m in py_from_import.finditer(content):
                mod = m.group(1).replace(".", "/")
                for target_rel in all_files:
                    if target_rel.startswith(mod) or target_rel == f"{mod}.py" or target_rel == f"{mod}/__init__.py":
                        edges.append((rel_path, target_rel))
            for m in py_import.finditer(content):
                mod = m.group(1).replace(".", "/")
                for target_rel in all_files:
                    if target_rel.startswith(mod) or target_rel == f"{mod}.py":
                        edges.append((rel_path, target_rel))
        else:
            for m in ts_import.finditer(content):
                target = m.group(1)
                # Resolve relative imports
                if target.startswith("."):
                    base_dir = Path(rel_path).parent
                    resolved = (base_dir / target).resolve()
                    for ext in ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"]:
                        cand = f"{resolved}{ext}"
                        if cand in all_files:
                            edges.append((rel_path, cand))

    return sorted(list(set(edges)))


class AnnotationIndex(Protocol):
    def file_summaries(self) -> Dict[str, str]: ...
    def summary(self, path: str) -> str: ...
    def chunks(self, path: str) -> List[Dict[str, Any]]: ...
    def import_edges(self) -> List[Tuple[str, str]]: ...
    def raw(self, path: str) -> str: ...


class RepositoryAnnotationIndex:
    def __init__(self, repo_dir: Path | str, store: Store, llm: Optional[Nemotron] = None):
        self.repo_dir = Path(repo_dir).resolve()
        self.store = store
        self.llm = llm or Nemotron()
        self._edges: Optional[List[Tuple[str, str]]] = None

    def raw(self, rel_path: str) -> str:
        """File-tier read; counts toward token counter file-tier tier (spec 13)."""
        file_path = self.repo_dir / rel_path
        if not file_path.exists():
            return ""
        log_usage("file_reader", "file_tier", 0, 0, tier_of_context="file")
        return file_path.read_text(encoding="utf-8", errors="replace")

    def summary(self, rel_path: str) -> str:
        data = self.store.get_annotation(rel_path)
        if data and "summary" in data:
            s = data["summary"]
            if isinstance(s, dict):
                return s.get("purpose", "")
            return str(s)
        return ""

    def file_summaries(self) -> Dict[str, str]:
        out = {}
        for p in self.repo_dir.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".js"} and not any(part.startswith(".") for part in p.parts):
                rel = str(p.relative_to(self.repo_dir))
                out[rel] = self.summary(rel) or f"Source file: {rel}"
        return out

    def chunks(self, rel_path: str) -> List[Dict[str, Any]]:
        data = self.store.get_annotation(rel_path)
        if data and "chunks" in data:
            return data["chunks"]
        return []

    def import_edges(self) -> List[Tuple[str, str]]:
        if self._edges is None:
            self._edges = extract_import_edges(self.repo_dir)
        return self._edges

    async def annotate_file(self, rel_path: str) -> FileAnnotations:
        """Run whole-file pass then line/chunk pass (spec 9)."""
        raw_text = self.raw(rel_path)
        if not raw_text:
            empty = FileAnnotations(
                path=rel_path,
                file_hash="",
                summary=WholeFileSummary(purpose="Empty or unreadable file"),
                chunks=[],
            )
            return empty

        file_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        # Check existing annotation and staleness
        existing = self.store.get_annotation(rel_path)
        if existing and existing.get("file_hash") == file_hash:
            return FileAnnotations.model_validate(existing)

        # 1. Whole-file pass
        sys_prompt = "You are the Annotator. Read the source file and summarize its purpose and structure. Never invent behavior."
        user_prompt = f"File: {rel_path}\n\n```\n{raw_text[:12000]}\n```\nSummarize this file."
        summary_out = await self.llm.structured("mid", sys_prompt, user_prompt, WholeFileSummary, agent="annotator", thinking=False)

        # 2. Chunking & Line pass (group by 5-15 lines)
        lines = raw_text.splitlines()
        chunks: List[ChunkComment] = []
        step = 10
        for i in range(0, len(lines), step):
            block = "\n".join(lines[i : i + step])
            if not block.strip():
                continue
            chash = compute_chunk_hash(block)
            chunks.append(
                ChunkComment(
                    chunk_hash=chash,
                    start_line=i + 1,
                    end_line=min(i + step, len(lines)),
                    comment=f"Lines {i+1}-{min(i+step, len(lines))}: implements logic in {summary_out.purpose[:60]}",
                    uncertain=False,
                )
            )

        annot = FileAnnotations(
            path=rel_path,
            file_hash=file_hash,
            summary=summary_out,
            chunks=chunks,
        )
        self.store.put_annotation(rel_path, annot.model_dump(), Actor.ENGINE)
        return annot
