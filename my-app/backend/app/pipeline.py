"""Automated pipeline for codebase pulling, commit diffing, requirement generation, and tenet grilling."""
import ast
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .actors import Actor
from .config import settings
from .events import emit
from .github import commit_summary, file_change
from .github_client import gh
from .intent.store import HYPOTHESIS, IntentStore, new_id


def compute_chunk_hash(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    norm = "\n".join(lines).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def extract_repo_files(sources: Dict[str, str], dest_dir: Path) -> int:
    """Extract source files to disk in the workspace repo directory."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path, content in sources.items():
        out_path = dest_dir / path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8", errors="replace")
        count += 1
    return count


NEMOTRON_MODELS = [
    os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"),
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3-ultra-550b-a55b",
]

def get_nemotron_client():
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv("my-app/.env")
        load_dotenv(".env")
        key = os.getenv("NVIDIA_API_KEY")
    if key and not key.startswith("apikey_"):
        try:
            from openai import OpenAI
            base_url = os.getenv("NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1")
            return OpenAI(base_url=base_url, api_key=key, timeout=30)
        except Exception:
            return None
    return None


def synthesize_annotation_with_nemotron(path: str, content: str) -> Optional[dict]:
    client = get_nemotron_client()
    if not client:
        return None
    prompt = f"""You are the NVIDIA Nemotron Architectural Intent Engine.
Analyze this source code file ({path}) from a software repository. Describe only what the code shows.

SOURCE CODE:
{content[:14000]}

Synthesize a comprehensive, production-grade architectural annotation conforming strictly to this JSON format:
{{
  "purpose": "A detailed 2-3 sentence explanation of the file's role, its boundaries, and what it does in this codebase.",
  "responsibilities": [
    "Detailed responsibility 1 (specific functions/classes, parameters, state updates)",
    "Detailed responsibility 2",
    "Detailed responsibility 3",
    "Detailed responsibility 4"
  ],
  "invariants": [
    "A rule the code visibly enforces (only if the code shows it)",
    "Another rule the code visibly enforces (omit if there are none)"
  ],
  "dependencies": ["imported_package_or_module_1", "imported_package_or_module_2"],
  "sections": ["Logical section 1", "Logical section 2", "Logical section 3"]
}}

Respond ONLY with the JSON object."""

    for model in NEMOTRON_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert system architect and invariant analyst. Output valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3500,
                temperature=0.1
            )
            if resp.choices and resp.choices[0].message:
                msg = resp.choices[0].message
                raw = (msg.content or getattr(msg, "reasoning_content", None) or "").strip()
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "```" in raw:
                    raw = raw.split("```")[1].split("```")[0].strip()
                elif "{" in raw and "}" in raw:
                    raw = raw[raw.find("{"):raw.rfind("}") + 1].strip()
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("purpose"):
                    return data
        except Exception:
            continue
    return None


def parse_code_structure(content: str, path: str) -> dict:
    """Extracts classes, functions, components, hooks, interfaces, and imports across languages."""
    lines = content.splitlines()
    loc = len(lines)

    if path.endswith(".py"):
        try:
            tree = ast.parse(content)
            doc = (ast.get_docstring(tree) or "").strip()
            classes = []
            funcs = []
            imports = []
            for n in tree.body:
                if isinstance(n, ast.Import):
                    imports.extend(alias.name for alias in n.names)
                elif isinstance(n, ast.ImportFrom):
                    if n.module:
                        imports.append(n.module)
                elif isinstance(n, ast.ClassDef):
                    cdoc = (ast.get_docstring(n) or "").strip()
                    methods = []
                    for m in n.body:
                        if isinstance(m, ast.FunctionDef):
                            mdoc = (ast.get_docstring(m) or "").strip()
                            methods.append({
                                "name": m.name,
                                "doc": mdoc.splitlines()[0] if mdoc else "",
                                "lineno": m.lineno,
                                "end_lineno": getattr(m, "end_lineno", m.lineno + 15),
                            })
                    classes.append({
                        "name": n.name,
                        "doc": cdoc.splitlines()[0] if cdoc else "",
                        "lineno": n.lineno,
                        "end_lineno": getattr(n, "end_lineno", n.lineno + 30),
                        "methods": methods,
                    })
                elif isinstance(n, ast.FunctionDef):
                    fdoc = (ast.get_docstring(n) or "").strip()
                    funcs.append({
                        "name": n.name,
                        "doc": fdoc.splitlines()[0] if fdoc else "",
                        "lineno": n.lineno,
                        "end_lineno": getattr(n, "end_lineno", n.lineno + 15),
                    })
            return {"doc": doc, "classes": classes, "funcs": funcs, "imports": sorted(list(set(imports))), "interfaces": []}
        except Exception:
            pass

    classes = []
    funcs = []
    imports = []
    interfaces = []

    # JS/TS/TSX parsing
    if any(path.endswith(ext) for ext in [".ts", ".tsx", ".js", ".jsx", ".mjs"]):
        for i, line in enumerate(lines, 1):
            imp_m = re.match(r"""import\s+(?:.*?\s+from\s+)?['"]([^'"]+)['"]""", line.strip())
            if imp_m:
                imports.append(imp_m.group(1))

            iface_m = re.match(r"""export\s+(?:interface|type)\s+([A-Za-z0-9_]+)""", line.strip())
            if iface_m:
                interfaces.append({"name": iface_m.group(1), "lineno": i, "end_lineno": min(i + 20, loc)})

            cls_m = re.match(r"""(?:export\s+)?class\s+([A-Za-z0-9_]+)""", line.strip())
            if cls_m:
                classes.append({"name": cls_m.group(1), "lineno": i, "end_lineno": min(i + 35, loc), "methods": []})

            if line.startswith("export ") or not line.startswith(" "):
                fn_m = re.match(r"""(?:export\s+)?(?:default\s+)?(?:function\s+([A-Za-z0-9_]+)|const\s+([A-Za-z0-9_]+)\s*(?:=|:\s*React\.FC))""", line.strip())
                if fn_m:
                    fname = fn_m.group(1) or fn_m.group(2)
                    funcs.append({"name": fname, "doc": f"Implements {fname} component and state handling", "lineno": i, "end_lineno": min(i + 35, loc)})

    # Rust parsing
    elif path.endswith(".rs"):
        for i, line in enumerate(lines, 1):
            use_m = re.match(r"""use\s+([a-zA-Z0-9_:]+)""", line.strip())
            if use_m:
                imports.append(use_m.group(1))
            st_m = re.match(r"""pub\s+(?:struct|enum)\s+([A-Za-z0-9_]+)""", line.strip())
            if st_m:
                classes.append({"name": st_m.group(1), "lineno": i, "end_lineno": min(i + 25, loc), "methods": []})
            fn_m = re.match(r"""(?:pub\s+)?fn\s+([A-Za-z0-9_]+)""", line.strip())
            if fn_m:
                funcs.append({"name": fn_m.group(1), "doc": "", "lineno": i, "end_lineno": min(i + 20, loc)})

    # SQL parsing
    elif path.endswith(".sql"):
        for i, line in enumerate(lines, 1):
            tbl_m = re.match(r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)""", line.strip(), re.IGNORECASE)
            if tbl_m:
                classes.append({"name": f"Table:{tbl_m.group(1)}", "lineno": i, "end_lineno": min(i + 20, loc), "methods": []})

    return {
        "doc": "",
        "classes": classes,
        "funcs": funcs,
        "interfaces": interfaces,
        "imports": sorted(list(set(imports)))[:15],
    }


def generate_annotations_for_file(path: str, content: str) -> dict:
    """Generate exhaustive, highly detailed file summary and chunk annotations feeding in exact lines of code."""
    lines = content.splitlines()
    loc = len(lines)
    base_name = os.path.basename(path)
    stem = os.path.splitext(base_name)[0]
    p_lower = path.lower()

    sem = parse_code_structure(content, path)
    classes = sem.get("classes", [])
    funcs = sem.get("funcs", [])
    interfaces = sem.get("interfaces", [])
    doc = sem.get("doc", "")
    imports = sem.get("imports", [])

    # 1. Exhaustive Architectural Purpose
    purpose_parts = []
    if doc:
        purpose_parts.append(doc)
    elif classes:
        c_names = ", ".join(c["name"] for c in classes[:2])
        purpose_parts.append(f"Core module defining {c_names} for {stem.replace('_', ' ')} domain capabilities and state operations.")
    elif funcs:
        f_names = ", ".join(f["name"] for f in funcs[:3])
        purpose_parts.append(f"Provides functional operations ({f_names}) for {stem.replace('_', ' ')} domain capabilities.")
    else:
        purpose_parts.append(f"Architectural subsystem module ({base_name}) providing {stem.replace('_', ' ')} capabilities.")

    purpose = " ".join(purpose_parts)

    # 2. Granular, Concrete Responsibilities
    responsibilities = []
    for c in classes:
        methods_str = f" with {len(c.get('methods', []))} method handlers" if c.get("methods") else ""
        responsibilities.append(f"Class {c['name']}: Implements domain state management and encapsulation{methods_str}.")
        for m in c.get("methods", []):
            if not m["name"].startswith("_"):
                m_doc = m["doc"] or f"executes {m['name'].replace('_', ' ')} operations"
                responsibilities.append(f"{c['name']}.{m['name']}(): {m_doc}.")

    for iface in interfaces:
        responsibilities.append(f"{iface['name']}: Enforces structural typing contract, required properties, and field type guards.")

    for f in funcs:
        if not f["name"].startswith("_"):
            f_doc = f["doc"] or f"executes {f['name'].replace('_', ' ')} logic"
            responsibilities.append(f"{f['name']}(): {f_doc}.")

    # No invented filler: an empty list is more honest than boilerplate (spec 10.1).

    # 3. Invariants: only rules read from the code by the LLM below; none are invented here.
    invariants: List[str] = []

    # 3b. Enrich with NVIDIA Nemotron when available
    nem = synthesize_annotation_with_nemotron(path, content)
    if nem and isinstance(nem, dict):
        if nem.get("purpose"):
            purpose = nem["purpose"]
        if nem.get("responsibilities"):
            responsibilities = nem["responsibilities"]
        if nem.get("invariants"):
            invariants = nem["invariants"]
        if nem.get("dependencies"):
            imports = nem["dependencies"]

    # 4. Sections & Chunks with Exact Code Snippets Fed In
    sections = []
    chunks = []

    anchors = []
    for iface in interfaces:
        anchors.append({"name": iface["name"], "start": iface["lineno"], "end": iface["end_lineno"], "kind": "interface"})
    for c in classes:
        anchors.append({"name": c["name"], "start": c["lineno"], "end": c["end_lineno"], "kind": "class"})
    for f in funcs:
        anchors.append({"name": f["name"], "start": f["lineno"], "end": f["end_lineno"], "kind": "function"})

    anchors.sort(key=lambda x: x["start"])

    covered = set()
    for anc in anchors:
        start = max(1, anc["start"])
        end = min(anc["end"], loc)
        if (start, end) in covered or start >= end:
            continue
        covered.add((start, end))

        chunk_lines = lines[start - 1 : end]
        chunk_code = "\n".join(chunk_lines)
        if not chunk_code.strip():
            continue

        sections.append(f"{anc['kind'].title()}: {anc['name']} (Lines {start}-{end})")
        chunks.append({
            "chunk_hash": compute_chunk_hash(chunk_code),
            "start_line": start,
            "end_line": end,
            "code_snippet": chunk_code,
            "comment": f"Lines {start}-{end}: {anc['kind']} '{anc['name']}'.",
            "uncertain": True,
        })

    # If file was not chunked by AST anchors, chunk systematically by logical slices
    if not chunks:
        step = 25
        for i in range(0, max(1, loc), step):
            start = i + 1
            end = min(i + step, loc)
            chunk_lines = lines[start - 1 : end]
            chunk_code = "\n".join(chunk_lines)
            if not chunk_code.strip():
                continue
            sections.append(f"Logical Block: Lines {start}-{end}")
            chunks.append({
                "chunk_hash": compute_chunk_hash(chunk_code),
                "start_line": start,
                "end_line": end,
                "code_snippet": chunk_code,
                "comment": f"Lines {start}-{end} of {base_name}.",
                "uncertain": True,
            })

    if not sections:
        sections = [f"{stem.title()} Implementation"]

    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "path": path,
        "file_hash": file_hash,
        "summary": {
            "purpose": purpose,
            "responsibilities": responsibilities[:15],
            "invariants": invariants[:5],
            "dependencies": imports[:15],
            "sections": sections[:12],
        },
        "chunks": chunks[:30],
    }


def _humanize(segment: str) -> str:
    stem = os.path.splitext(segment)[0]
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem).replace("_", " ").replace("-", " ").split()
    return " ".join(w if w.isupper() else w.capitalize() for w in words) or segment


def _purpose_of(store: Optional[IntentStore], path: str) -> str:
    if store is None:
        return ""
    s = (store.get_annotation(path) or {}).get("summary")
    text = s.get("purpose", "") if isinstance(s, dict) else (s or "")
    return re.sub(r"\s+", " ", str(text)).strip()


def classify_subsystem(grp: str, file_paths: List[str], repo_sources: Optional[Dict[str, str]] = None,
                       store: Optional[IntentStore] = None) -> Tuple[str, str, List[dict]]:
    """Name and describe a group of files from their own annotations.

    Returns no claims: Hypotheses come from grilling the user (spec 10.2), and test
    recipes from the Test Author, so nothing here is pre-written or repo-specific.
    """
    purposes = [p for p in (_purpose_of(store, f) for f in sorted(file_paths)[:4]) if p]
    if purposes:
        functionality = " ".join(purposes)[:700]
    else:
        shown = ", ".join(sorted(file_paths)[:5])
        functionality = f"Code in {grp}/: {shown}{' and more' if len(file_paths) > 5 else ''}."
    name = "Core" if grp.lower() in ("src", "lib", "app", "source", "core", "main") else _humanize(grp)
    return name, functionality, []


def _name_features(store: IntentStore, repo_title: str, groups: Dict[str, List[str]]) -> Tuple[str, Dict[str, dict]]:
    """One LLM call to name the top-level features and draft the system purpose. Empty without a key."""
    from .grill import SYSTEM_PROMPT, _llm_json

    listing = []
    for grp, paths in sorted(groups.items()):
        listing.append(f"[{grp}]")
        for p in sorted(paths)[:8]:
            purpose = _purpose_of(store, p)[:160]
            listing.append(f"  - {p}{': ' + purpose if purpose else ''}")
    data = _llm_json(SYSTEM_PROMPT, f"""Repository: {repo_title}
Its code, grouped by folder:
{chr(10).join(listing)[:12000]}

Draft "system": 1-2 sentences on what this codebase is for overall, and for each folder group a
user-facing feature name (2-5 words) and one paragraph of what it does, based only on the code.
JSON: {{"system": "...", "features": [{{"group": "<folder group exactly as given>", "name": "...", "functionality": "..."}}]}}""")
    if not data:
        return "", {}
    features = {
        str(f.get("group")): f for f in data.get("features") or []
        if isinstance(f, dict) and f.get("group") in groups and str(f.get("name", "")).strip()
    }
    return str(data.get("system") or "").strip(), features


def generate_requirements_and_tenets(store: IntentStore, snapshot: dict, full_name: str, sources: Optional[Dict[str, str]] = None) -> dict:
    """Create the respective codebase requirements/files: Tenets, Claims, Code Links, and Spec."""
    actor_engine = Actor(kind="engine", name="pipeline")
    actor_builder = Actor(kind="builder", name="pipeline")

    tenets = store.tenets()
    if tenets:
        root_id = next((t["id"] for t in tenets.values() if t["parent_id"] is None), None)
        return {
            "root_id": root_id,
            "created_tenets": [],
            "created_claims": [],
        }

    # 1. Root Tenet
    root_id = None
    for t in tenets.values():
        if t["parent_id"] is None:
            root_id = t["id"]
            break

    created_tenets = []
    created_claims = []
    repo_title = full_name.split("/")[-1].replace("-", " ").replace("_", " ").title()

    # Group files into top-level areas; these become the first level (features) of the hierarchy.
    groups: Dict[str, List[str]] = {}
    for f in snapshot.get("files", []):
        p = f["path"]
        parts = p.split("/")
        if len(parts) > 1:
            grp = parts[0] if parts[0] not in ("src", "lib", "app") else (parts[1] if len(parts) > 2 else parts[0])
        else:
            grp = "core"
        groups.setdefault(grp, []).append(p)

    system_purpose, feature_names = _name_features(store, repo_title, groups)

    if root_id is None:
        root = store.create_tenet(
            actor_builder,
            repo_title,
            system_purpose or (
                f"Draft: {repo_title} as a whole, covering {len(snapshot.get('files', []))} files in "
                f"{len(groups)} areas ({', '.join(sorted(groups)[:6])}). Grilling confirms or corrects this."
            ),
            None,
            [],
            {"via": "pipeline"},
        )
        root_id = root["id"]
        created_tenets.append(root_id)

    # 2. Sub-tenets, code links, and requirement claims
    tenets = store.tenets()
    existing_names = {t["name"].lower(): t["id"] for t in tenets.values()}

    for grp, paths in sorted(groups.items()):
        sub_name, sub_func, candidate_claims = classify_subsystem(grp, paths, sources, store)
        if grp in feature_names:
            sub_name = str(feature_names[grp]["name"]).strip()[:200]
            sub_func = str(feature_names[grp].get("functionality") or sub_func).strip()
        if sub_name.lower() in existing_names:
            t_id = existing_names[sub_name.lower()]
        else:
            sub = store.create_tenet(
                actor_builder,
                sub_name,
                sub_func,
                root_id,
                [],
                {"via": "pipeline"},
            )
            t_id = sub["id"]
            created_tenets.append(t_id)
            existing_names[sub_name.lower()] = t_id

        # Attach code links to leaf tenets (merge paths, do not discard)
        t_obj = store.tenet(t_id)
        existing_links = {l.get("path") for l in t_obj.get("code_links", []) if l.get("path")}
        new_links = list(t_obj.get("code_links", []))
        for p in sorted(paths):  # every file, so the hierarchy below covers all of the code
            if p not in existing_links:
                new_links.append({"path": p})
                existing_links.add(p)
        store.set_links(actor_engine, t_id, new_links)

        # Every new Tenet starts with a Hypothesis drawn from its code (no Axiom is required).
        from .grill import ensure_hypothesis
        new_claim = ensure_hypothesis(store, t_id, "pipeline")
        if new_claim:
            created_claims.append(new_claim)

    if root_id:
        from .grill import ensure_hypothesis
        new_claim = ensure_hypothesis(store, root_id, "pipeline")
        if new_claim:
            created_claims.append(new_claim)

    # 3. Compile Spec document with code links and annotations
    sections = []
    for t in store.tenets().values():
        links = t.get("code_links", [])
        annots = []
        for l in links:
            lp = l.get("path") or l.get("file")
            if lp:
                a = store.get_annotation(lp)
                if a and "summary" in a:
                    s = a["summary"]
                    purpose = s.get("purpose", "") if isinstance(s, dict) else str(s)
                    resp = s.get("responsibilities", []) if isinstance(s, dict) else []
                    annots.append({"path": lp, "purpose": purpose, "responsibilities": resp})

        sections.append({
            "tenet_id": t["id"],
            "name": t["name"],
            "functionality": t["functionality"],
            "code_links": links,
            "annotations": annots,
            "requirements": [
                {
                    "id": cid,
                    "statement": store.claim(cid)["statement"],
                    "status": store.claim(cid)["status"],
                }
                for cid in t["claims"]
            ],
        })

    spec_data = {
        "title": f"{repo_title} Requirements Specification",
        "compiled_at": time.time(),
        "root_tenet": root_id,
        "tenets_count": len(store.tenets()),
        "claims_count": len(store.claims()),
        "sections": sections,
    }
    spec_dir = store._path("spec")
    spec_dir.mkdir(parents=True, exist_ok=True)
    store._write(spec_dir / "compiled.json", spec_data)

    return {
        "root_id": root_id,
        "created_tenets": created_tenets,
        "created_claims": created_claims,
    }


def start_tenet_grilling_session(workspace_id: int, store: IntentStore, root_id: str, full_name: str) -> dict:
    """Start grilling at the root, or carry on with a session that is already in progress.

    The pipeline re-runs after syncs and whenever the UI refreshes; restarting here would wipe
    the user's answers. Starting over is an explicit choice: POST .../grill/start.
    """
    from . import grill
    current = grill.load_grill_state(workspace_id)
    if current and not current.get("done") and current.get("tenet_id") in store.tenets():
        return grill._public(current)
    return grill.start_grill_session(workspace_id, tenet_id=root_id, full_name=full_name)


async def execute_full_pipeline(
    workspace_id: int,
    token: str,
    full_name: str,
    head_sha: str,
    base_sha: Optional[str] = None,
) -> dict:
    """Executes the complete 4-step pipeline:

    1. Pull the code (download and extract sources to workspace disk).
    2. Check diffs from the most recent commit.
    3. Make respective codebase requirements / files (annotations, tenets, claims, spec).
    4. Start the tenet grilling process.
    """
    store = IntentStore(workspace_id)
    actor_engine = Actor(kind="engine", name="pipeline")
    repo_dir = Path(settings.data_dir) / "workspaces" / str(workspace_id) / "repo"

    # Step 1: Pull the code
    from . import codebase
    tarball_data = await codebase.fetch_tarball(token, full_name, head_sha)
    files, sources = codebase.read_tarball(tarball_data)
    extracted_count = extract_repo_files(sources, repo_dir)
    snapshot = codebase.build_snapshot(files, sources, head_sha)
    store.put_imports(snapshot)

    # Step 2: Check diffs from the most recent commit
    diff_files = []
    diff_commits = []
    if base_sha and base_sha != head_sha:
        from .github import compare_refs
        try:
            cmp_res = await compare_refs(token, full_name, base_sha, head_sha)
            diff_files = cmp_res.get("files", [])
            diff_commits = cmp_res.get("commits", [])
        except Exception:
            pass

    if not diff_files:
        try:
            head_commit = await gh(token, "GET", f"/repos/{full_name}/commits/{head_sha}")
            if head_commit and "files" in head_commit:
                diff_files = [file_change(f) for f in head_commit.get("files", [])]
                diff_commits = [commit_summary(head_commit)]
        except Exception:
            pass

    # Step 3: Make respective codebase requirements / files
    # 3a. Generate annotations
    annot_count = 0
    for path, content in sources.items():
        if codebase.language(path):
            existing = store.get_annotation(path)
            has_snippets = existing and any("code_snippet" in c for c in existing.get("chunks", []))
            if not existing or not has_snippets:
                annot = generate_annotations_for_file(path, content)
                store.put_annotation(actor_engine, path, annot)
                annot_count += 1

    # 3b. Generate Tenets, Claims, and Spec
    req_res = generate_requirements_and_tenets(store, snapshot, full_name, sources)

    # Step 4: Start the tenet grilling process
    grill_state = start_tenet_grilling_session(workspace_id, store, req_res["root_id"], full_name)

    return {
        "status": "success",
        "pulled_code": {
            "files_extracted": extracted_count,
            "total_files": len(files),
            "repo_dir": str(repo_dir),
            "head": head_sha,
        },
        "diff": {
            "base": base_sha,
            "head": head_sha,
            "files": diff_files,
            "commits": diff_commits,
            "changed_files_count": len(diff_files),
        },
        "requirements": {
            "annotations_created": annot_count,
            "tenets_created": len(req_res["created_tenets"]),
            "claims_created": len(req_res["created_claims"]),
            "root_tenet_id": req_res["root_id"],
            "spec_compiled": True,
        },
        "grill": {
            "session_id": grill_state["id"],
            "tenet_id": grill_state["tenet_id"],
            "tenet_name": grill_state.get("tenet_name"),
            "level": grill_state.get("level", 0),
            "level_name": grill_state.get("level_name"),
            "questions_count": len(grill_state["questions"]),
            "questions": grill_state["questions"],
        },
    }
