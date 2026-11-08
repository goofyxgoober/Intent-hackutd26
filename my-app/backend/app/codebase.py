"""Codebase snapshot: file tree and import edges by pattern matching (spec section 9).

No LLM is involved: edges come from a small rule set per language, so the
Codebase view's edges are reliable. Supported: Python and TypeScript/JavaScript.
"""
import io
import json
from pathlib import Path
import posixpath
import re
import tarfile
from typing import Dict, List, Optional, Set, Tuple

from fastapi import HTTPException

from . import github_client

MAX_TARBALL_BYTES = 100_000_000
MAX_SOURCE_BYTES = 1_000_000

PY_EXT = (".py",)
TS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
TS_RESOLVE = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs")


def language(path: str) -> Optional[str]:
    if path.endswith(PY_EXT):
        return "python"
    if path.endswith((".ts", ".tsx")):
        return "typescript"
    if path.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return "javascript"
    return None


# ------------------------------------------------------------------ fetching


async def fetch_tarball(token: str, full_name: str, ref: str) -> bytes:
    async with github_client.client() as c:
        res = await c.get(
            f"/repos/{full_name}/tarball/{ref}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            follow_redirects=True,
        )
    if res.status_code == 404:
        raise HTTPException(404, f"GitHub: {full_name}@{ref} not found or no access")
    if not res.is_success:
        raise HTTPException(502, f"GitHub tarball download failed ({res.status_code})")
    if len(res.content) > MAX_TARBALL_BYTES:
        raise HTTPException(413, "Repository archive is larger than 100 MB")
    return res.content


def read_tarball(data: bytes) -> Tuple[List[dict], Dict[str, str]]:
    """All file paths with sizes, and the text of source files we can parse."""
    files: List[dict] = []
    sources: Dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile() or "/" not in m.name:
                continue
            path = m.name.split("/", 1)[1]  # drop the "owner-repo-sha/" prefix
            if not path:
                continue
            files.append({"path": path, "size": m.size, "language": language(path)})
            if (language(path) or path.endswith("tsconfig.json")) and m.size <= MAX_SOURCE_BYTES:
                f = tar.extractfile(m)
                if f is not None:
                    sources[path] = f.read().decode("utf-8", errors="replace")
    files.sort(key=lambda f: f["path"])
    return files, sources


# ------------------------------------------------------------------ Python


PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]+as[ \t]+\w+)?(?:[ \t]*,[ \t]*[\w.]+(?:[ \t]+as[ \t]+\w+)?)*)", re.M)
PY_FROM = re.compile(r"^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(?:\(([^)]*)\)|([^\n#]*))", re.M)


def _py_candidates(base: str) -> List[str]:
    return [f"{base}.py", f"{base}/__init__.py"] if base else []


def _resolve_py_module(parts: List[str], importer: str, files: Set[str]) -> Optional[str]:
    dotted = "/".join(parts)
    # 1. next to the importer (scripts importing siblings)
    here = posixpath.dirname(importer)
    for cand in _py_candidates(posixpath.join(here, dotted) if here else dotted):
        if cand in files:
            return cand
    # 2. from the repo root
    for cand in _py_candidates(dotted):
        if cand in files:
            return cand
    # 3. from a source root such as src/: unique match on the path suffix
    suffixes = [f"/{c}" for c in _py_candidates(dotted)]
    hits = [f for f in files if any(f.endswith(s) for s in suffixes)]
    return hits[0] if len(hits) == 1 else None


def python_imports(path: str, source: str, files: Set[str]) -> Tuple[Set[str], Set[str]]:
    edges: Set[str] = set()
    external: Set[str] = set()
    for m in PY_IMPORT.finditer(source):
        for item in m.group(1).split(","):
            mod = item.strip().split()[0]
            target = _resolve_py_module(mod.split("."), path, files)
            (edges.add(target) if target else external.add(mod.split(".")[0]))
    for m in PY_FROM.finditer(source):
        dots, mod = m.group(1), m.group(2)
        names = [n.strip().split()[0] for n in (m.group(3) or m.group(4) or "").replace("\n", " ").split(",") if n.strip()]
        if dots:
            pkg = posixpath.dirname(path)
            for _ in range(len(dots) - 1):
                pkg = posixpath.dirname(pkg)
            base = posixpath.join(pkg, *mod.split(".")) if mod else pkg
            found = False
            for name in names:
                for cand in _py_candidates(posixpath.join(base, name)):
                    if cand in files:
                        edges.add(cand)
                        found = True
            if not found:
                for cand in _py_candidates(base):
                    if cand in files:
                        edges.add(cand)
                        break
            continue
        parts = mod.split(".")
        found = False
        for name in names:
            if name != "*":
                target = _resolve_py_module(parts + [name], path, files)
                if target:
                    edges.add(target)
                    found = True
        if not found:
            target = _resolve_py_module(parts, path, files)
            (edges.add(target) if target else external.add(parts[0]))
    edges.discard(path)
    return edges, external


# ------------------------------------------------------------------ TypeScript / JavaScript


TS_STATIC = re.compile(r"""(?:^|[;\s])(?:import|export)\s+(?:type\s+)?(?:[\w*{}\s,$]+?\s+from\s+)?["']([^"'\n]+)["']""")
TS_DYNAMIC = re.compile(r"""(?:\bimport|\brequire)\s*\(\s*["']([^"'\n]+)["']\s*\)""")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)


def _strip_jsonc(text: str) -> str:
    text = BLOCK_COMMENT.sub("", text)
    text = re.sub(r'(?m)^\s*//.*$|(?<=[,{\[\s])//[^\n"]*$', "", text)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def load_tsconfigs(sources: Dict[str, str]) -> Dict[str, dict]:
    """tsconfig dir -> {"base": baseUrl dir, "paths": {...}}."""
    out = {}
    for path, text in sources.items():
        if not path.endswith("tsconfig.json"):
            continue
        try:
            opts = json.loads(_strip_jsonc(text)).get("compilerOptions", {})
        except ValueError:
            continue
        here = posixpath.dirname(path)
        base = posixpath.normpath(posixpath.join(here, opts.get("baseUrl", "."))) if (opts.get("baseUrl") or opts.get("paths")) else None
        out[here] = {"base": None if base == "." and not here else base, "paths": opts.get("paths") or {}, "has_base": "baseUrl" in opts}
    return out


def _nearest_tsconfig(path: str, configs: Dict[str, dict]) -> Optional[dict]:
    d = posixpath.dirname(path)
    while True:
        if d in configs:
            return configs[d]
        if not d:
            return None
        d = posixpath.dirname(d)


def _resolve_ts_file(base: str, files: Set[str]) -> Optional[str]:
    base = posixpath.normpath(base)
    if base.startswith("../") or base == "..":
        return None
    base = "" if base == "." else base
    if base in files:
        return base
    stem = re.sub(r"\.(js|jsx|mjs|cjs)$", "", base)  # TS lets "./x.js" mean "./x.ts"
    for ext in TS_RESOLVE:
        if stem + ext in files:
            return stem + ext
    for ext in TS_RESOLVE:
        cand = posixpath.join(base, "index" + ext) if base else "index" + ext
        if cand in files:
            return cand
    return None


def _package_name(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


def ts_imports(path: str, source: str, files: Set[str], configs: Dict[str, dict]) -> Tuple[Set[str], Set[str]]:
    edges: Set[str] = set()
    external: Set[str] = set()
    text = LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", source))
    specs = {m.group(1) for m in TS_STATIC.finditer(text)} | {m.group(1) for m in TS_DYNAMIC.finditer(text)}
    config = _nearest_tsconfig(path, configs)
    for spec in specs:
        target = None
        if spec.startswith("."):
            target = _resolve_ts_file(posixpath.join(posixpath.dirname(path), spec), files)
        elif config:
            root = config["base"] if config["base"] is not None else ""
            for pattern, targets in config["paths"].items():
                prefix = pattern[:-1] if pattern.endswith("*") else pattern
                if (pattern.endswith("*") and spec.startswith(prefix)) or spec == pattern:
                    rest = spec[len(prefix):] if pattern.endswith("*") else ""
                    for t in targets:
                        target = _resolve_ts_file(posixpath.join(root, t.replace("*", rest)), files)
                        if target:
                            break
                if target:
                    break
            if not target and config["has_base"]:
                target = _resolve_ts_file(posixpath.join(root, spec), files)
        if target:
            edges.add(target)
        elif not spec.startswith("."):
            external.add(_package_name(spec))
    edges.discard(path)
    return edges, external


# ------------------------------------------------------------------ snapshot


def build_snapshot(files: List[dict], sources: Dict[str, str], head: str) -> dict:
    paths = {f["path"] for f in files}
    configs = load_tsconfigs(sources)
    edges: List[dict] = []
    external: List[dict] = []
    for path, source in sorted(sources.items()):
        lang = language(path)
        if lang == "python":
            internal, ext = python_imports(path, source, paths)
        elif lang in ("typescript", "javascript"):
            internal, ext = ts_imports(path, source, paths, configs)
        else:
            continue
        edges += [{"source": path, "target": t} for t in sorted(internal)]
        external += [{"source": path, "package": p} for p in sorted(ext)]
    return {"head": head, "files": files, "edges": edges, "external": external}


def extract_repo(sources: Dict[str, str], dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path, content in sources.items():
        out_p = dest_dir / path
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8", errors="replace")


async def snapshot_repo(token: str, full_name: str, ref: str, extract_dir: Optional[Path] = None) -> dict:
    files, sources = read_tarball(await fetch_tarball(token, full_name, ref))
    if extract_dir is not None:
        extract_repo(sources, extract_dir)
    return build_snapshot(files, sources, ref)
