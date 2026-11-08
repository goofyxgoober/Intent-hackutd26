"""The intent folder (spec section 6) and the rules that guard it (sections 3, 7, 8).

Every write goes through this module, and every rule is checked here, so an agent
can't break a rule by wording a prompt cleverly. Files are JSON:

  tenets/<tenet_id>.json            one per Tenet
  claims/<tenet_id>/<claim_id>.json one per Claim (Axiom, Hypothesis or scrapped)
  results/<claim_id>.json           append-only test runs, plus results/index.json
  annotations/<repo path>.json      Annotator output per source file
  links/                            code links, import edges, reverse indexes
  history/                          Axiom snapshots, scrapped Hypotheses, rejected interpretations
  spec/                             compiled spec
  changelog/changelog.jsonl         Jev decisions and user status changes
"""
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from fastapi import HTTPException

from ..actors import Actor
from ..errors import EngineError
from ..config import settings
from .. import events

AXIOM, HYPOTHESIS, SCRAPPED = "axiom", "hypothesis", "scrapped"
AGENT_TENET_WRITERS = ("user", "builder", "engine")
HYPOTHESIS_WRITERS = ("user", "builder", "engine")

_locks: Dict[int, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock(workspace_id: int) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(workspace_id, threading.RLock())


def _now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def content_hash(claim: dict) -> str:
    """Hash of the statement and test sections; results bind to it (rule 6)."""
    body = json.dumps([claim["statement"], claim["test_explanation"], claim["test_implementation"]])
    return hashlib.sha256(body.encode()).hexdigest()


def forbid(message: str, code: str = "PERMISSION_DENIED") -> HTTPException:
    return EngineError(403, message, code)


def conflict(message: str, code: str = "CONFLICT", **extra) -> HTTPException:
    return EngineError(409, {"message": message, **extra} if extra else message, code)


def safe_repo_path(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise HTTPException(422, f"Not a valid repository path: {path!r}")
    return path


class IntentStore:
    def __init__(self, workspace_id: int):
        self.wid = workspace_id
        self.root = Path(settings.data_dir) / "workspaces" / str(workspace_id) / "intent"
        self.lock = _lock(workspace_id)

    # ------------------------------------------------------------------ files

    def _path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def _read(self, path: Path, default=None):
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return default

    def _write(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=False))
        os.replace(tmp, path)

    def _append_jsonl(self, path: Path, entry: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def _read_jsonl(self, path: Path) -> List[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    # ------------------------------------------------------------------ loading

    def tenets(self) -> Dict[str, dict]:
        out = {}
        for f in self._path("tenets").glob("*.json"):
            t = json.loads(f.read_text())
            out[t["id"]] = t
        return out

    def claims(self, include_scrapped: bool = False) -> Dict[str, dict]:
        out = {}
        for f in self._path("claims").glob("*/*.json"):
            c = json.loads(f.read_text())
            if include_scrapped or c["status"] != SCRAPPED:
                out[c["id"]] = c
        return out

    def tenet(self, tid: str) -> dict:
        t = self._read(self._path("tenets", f"{tid}.json"))
        if t is None:
            raise HTTPException(404, f"No Tenet {tid}")
        return t

    def claim(self, cid: str) -> dict:
        index = self._read(self._path("results", "index.json"), {})
        entry = index.get(cid)
        c = self._read(self._path("claims", entry["tenet_id"], f"{cid}.json")) if entry else None
        if c is None:
            raise HTTPException(404, f"No Claim {cid}")
        return c

    def _save_tenet(self, t: dict) -> None:
        t["updated_at"] = _now()
        self._write(self._path("tenets", f"{t['id']}.json"), t)

    def _save_claim(self, c: dict) -> None:
        c["updated_at"] = _now()
        c["content_hash"] = content_hash(c)
        self._write(self._path("claims", c["tenet_id"], f"{c['id']}.json"), c)
        index = self._read(self._path("results", "index.json"), {})
        index[c["id"]] = {"tenet_id": c["tenet_id"], "claim_path": f"claims/{c['tenet_id']}/{c['id']}.json"}
        self._write(self._path("results", "index.json"), index)

    # ------------------------------------------------------------------ derived structure

    @staticmethod
    def level(tenets: Dict[str, dict], tid: str) -> int:
        depth, cur = 0, tenets[tid]
        while cur.get("parent_id"):
            depth, cur = depth + 1, tenets[cur["parent_id"]]
        return depth

    @staticmethod
    def ancestors(tenets: Dict[str, dict], tid: str) -> List[str]:
        out, cur = [], tenets[tid].get("parent_id")
        while cur:
            out.append(cur)
            cur = tenets[cur].get("parent_id")
        return out

    @staticmethod
    def descendants(tenets: Dict[str, dict], tid: str) -> Set[str]:
        out, stack = set(), list(tenets[tid]["children"])
        while stack:
            cur = stack.pop()
            if cur not in out:
                out.add(cur)
                stack.extend(tenets[cur]["children"])
        return out

    @staticmethod
    def referencers(tenets: Dict[str, dict], tid: str) -> List[str]:
        return [t["id"] for t in tenets.values() if tid in t["references"] or tid in t["cross_cutting"]]

    def footprint(self, tenets: Dict[str, dict], tid: str, seen: Optional[Set[str]] = None) -> List[dict]:
        """Leaves carry links; a higher Tenet's footprint is the union below it (section 4.3)."""
        seen = seen if seen is not None else set()
        if tid in seen:
            return []
        seen.add(tid)
        t = tenets[tid]
        if not t["children"]:
            return list(t["code_links"])
        out: List[dict] = []
        for other in t["children"] + t["references"] + t["cross_cutting"]:
            out.extend(self.footprint(tenets, other, seen))
        return out

    def upward(self, tenets: Dict[str, dict], tid: str) -> Set[str]:
        """Every Tenet whose integration Claims can be touched by a change in `tid`."""
        out, stack = set(), [tid]
        while stack:
            cur = stack.pop()
            for nxt in self.ancestors(tenets, cur) + self.referencers(tenets, cur):
                if nxt not in out:
                    out.add(nxt)
                    stack.append(nxt)
        out.discard(tid)
        return out

    def _composition_edges(self, tenets: Dict[str, dict]) -> Dict[str, Set[str]]:
        return {t["id"]: set(t["children"]) | set(t["references"]) | set(t["cross_cutting"]) for t in tenets.values()}

    @staticmethod
    def _has_cycle(edges: Dict[str, Set[str]]) -> bool:
        state: Dict[str, int] = {}

        def visit(n: str) -> bool:
            state[n] = 1
            for m in edges.get(n, ()):
                if state.get(m) == 1 or (state.get(m) is None and visit(m)):
                    return True
            state[n] = 2
            return False

        return any(state.get(n) is None and visit(n) for n in list(edges))

    def _write_indexes(self) -> None:
        """Engine-generated reverse indexes in links/ (section 6)."""
        tenets, claims = self.tenets(), self.claims()
        refs: Dict[str, List[str]] = {}
        for t in tenets.values():
            for target in t["references"] + t["cross_cutting"]:
                refs.setdefault(target, []).append(t["id"])
        deps: Dict[str, List[str]] = {}
        for c in claims.values():
            for d in c["dependencies"]:
                deps.setdefault(d, []).append(c["id"])
        code: Dict[str, List[str]] = {}
        for t in tenets.values():
            for link in t["code_links"]:
                code.setdefault(link["path"], []).append(t["id"])
        self._write(self._path("links", "references.json"), refs)
        self._write(self._path("links", "dependencies.json"), deps)
        self._write(self._path("links", "code_links.json"), {
            "by_tenet": {t["id"]: t["code_links"] for t in tenets.values() if t["code_links"]},
            "by_file": code,
        })

    def dependents(self, cid: str, claims: Dict[str, dict], transitive: bool = True) -> List[str]:
        out: List[str] = []
        frontier = [cid]
        while frontier:
            cur = frontier.pop()
            for c in claims.values():
                if cur in c["dependencies"] and c["id"] not in out:
                    out.append(c["id"])
                    if transitive:
                        frontier.append(c["id"])
        return out

    # ------------------------------------------------------------------ results

    def result_file(self, cid: str) -> dict:
        return self._read(self._path("results", f"{cid}.json"), None) or {
            "claim_id": cid, "runs": [], "invalidations": [],
        }

    def summarize_result(self, claim: dict, rf: Optional[dict] = None) -> dict:
        rf = rf or self.result_file(claim["id"])
        runs = rf["runs"]
        # Determinism check (section 5): identical runs = same wording and same code.
        code_ref = runs[-1].get("code_ref") if runs else None
        identical = [r for r in runs if r["claim_hash"] == claim["content_hash"] and r.get("code_ref") == code_ref]
        flaky = len({r["verdict"] for r in identical if r["verdict"] in ("pass", "fail")}) > 1
        if not runs:
            verdict = "untested"
        else:
            last = runs[-1]
            invalidated = rf["invalidations"] and rf["invalidations"][-1]["at"] >= last["at"]
            verdict = "stale" if last["claim_hash"] != claim["content_hash"] or invalidated else last["verdict"]
        return {"verdict": verdict, "flaky": flaky, "runs": len(runs),
                "last_run_at": runs[-1]["at"] if runs else None}

    def _invalidate_results(self, cids: Iterable[str], reason: str) -> List[str]:
        touched = []
        for cid in cids:
            rf = self.result_file(cid)
            if rf["runs"]:
                rf["invalidations"].append({"at": _now(), "reason": reason})
                self._write(self._path("results", f"{cid}.json"), rf)
                touched.append(cid)
        return touched

    # ------------------------------------------------------------------ views

    def tree(self) -> dict:
        tenets, claims = self.tenets(), self.claims()
        claim_out = {}
        for c in claims.values():
            claim_out[c["id"]] = {**c, "result": self.summarize_result(c)}
        tenet_out = []
        for t in tenets.values():
            own = [claim_out[c] for c in t["claims"] if c in claim_out]
            verdicts = [c["result"]["verdict"] for c in own]
            rollup = ("empty" if not verdicts else "fail" if "fail" in verdicts else "stale" if "stale" in verdicts
                      else "inconclusive" if any(v in ("inconclusive", "untested") for v in verdicts) else "pass")
            tenet_out.append({
                **t,
                "level": self.level(tenets, t["id"]),
                "is_leaf": not t["children"],
                "referenced_by": self.referencers(tenets, t["id"]),
                "axioms": sum(c["status"] == AXIOM for c in own),
                "hypotheses": sum(c["status"] == HYPOTHESIS for c in own),
                "flagged_axioms": sum(c["status"] == AXIOM and bool(c["flags"]) for c in own),
                "rollup": rollup,
            })
        roots = [t["id"] for t in tenets.values() if not t.get("parent_id")]
        return {"root_id": roots[0] if roots else None, "tenets": tenet_out, "claims": claim_out}

    # ------------------------------------------------------------------ logs

    def changelog(self, entry: dict) -> None:
        self._append_jsonl(self._path("changelog", "changelog.jsonl"), {"at": _now(), **entry})

    def read_changelog(self, limit: int = 200) -> List[dict]:
        return self._read_jsonl(self._path("changelog", "changelog.jsonl"))[-limit:]

    def _history(self, kind: str, record: dict) -> None:
        name = f"{int(_now() * 1000)}-{record.get('id', 'entry')}.json"
        self._write(self._path("history", kind, name), {"recorded_at": _now(), **record})

    def history(self, kind: Optional[str] = None) -> List[dict]:
        pattern = f"{kind}/*.json" if kind else "*/*.json"
        files = sorted(self._path("history").glob(pattern))
        return [{"kind": f.parent.name, **json.loads(f.read_text())} for f in files]

    def _emit(self, event: str, **data) -> None:
        events.emit(self.wid, event, **data)

    # ------------------------------------------------------------------ Tenets

    def create_tenet(self, actor: Actor, name: str, functionality: str, parent_id: Optional[str],
                     cross_cutting: List[str], provenance: dict) -> dict:
        if actor.kind not in AGENT_TENET_WRITERS:
            raise forbid(f"{actor.kind} can't create Tenets")
        with self.lock:
            tenets = self.tenets()
            if parent_id is None:
                if any(not t.get("parent_id") for t in tenets.values()):
                    raise conflict("A root Tenet already exists; give this Tenet a parent_id")
            else:
                parent = tenets.get(parent_id) or self.tenet(parent_id)
                if parent["code_links"]:
                    raise conflict(f"{parent_id} is a leaf with code links. Clear its links before adding children.")
            for x in cross_cutting:
                if x not in tenets:
                    raise HTTPException(422, f"No Tenet {x}")
            t = {
                "id": new_id("t"), "name": name, "parent_id": parent_id, "provenance": actor.provenance(provenance),
                "proposed": provenance.get("via") == "sync" or actor.kind == "engine",
                "functionality": functionality, "children": [], "references": [], "cross_cutting": cross_cutting,
                "code_links": [], "claims": [], "created_at": _now(),
            }
            tenets[t["id"]] = t
            if parent_id:
                tenets[parent_id]["children"].append(t["id"])
            if self._has_cycle(self._composition_edges(tenets)):
                raise conflict("That would create a reference cycle")
            self._save_tenet(t)
            if parent_id:
                self._save_tenet(tenets[parent_id])
            self._write_indexes()
        self._emit("tenet.created", tenet_id=t["id"])
        return t

    def update_tenet(self, actor: Actor, tid: str, fields: dict) -> dict:
        if actor.kind not in AGENT_TENET_WRITERS:
            raise forbid(f"{actor.kind} can't edit Tenets")
        with self.lock:
            tenets = self.tenets()
            t = tenets.get(tid) or self.tenet(tid)
            if fields.get("children") is not None:
                if sorted(fields["children"]) != sorted(t["children"]):
                    raise HTTPException(422, "children can only be reordered here; use move to change ownership")
                t["children"] = fields["children"]
            if fields.get("cross_cutting") is not None:
                for x in fields["cross_cutting"]:
                    if x not in tenets or x == tid:
                        raise HTTPException(422, f"Not a valid cross-cutting Tenet: {x}")
                t["cross_cutting"] = fields["cross_cutting"]
                if self._has_cycle(self._composition_edges(tenets)):
                    raise conflict("That would create a reference cycle")
            for key in ("name", "functionality"):
                if fields.get(key) is not None:
                    t[key] = fields[key]
            if actor.is_user:
                t["proposed"] = False
            self._save_tenet(t)
            self._write_indexes()
        self._emit("tenet.updated", tenet_id=tid)
        return t

    def _holds_axioms(self, tid: str, claims: Dict[str, dict]) -> List[str]:
        return [c["id"] for c in claims.values() if c["tenet_id"] == tid and c["status"] == AXIOM]

    def move_tenet(self, actor: Actor, tid: str, new_parent: str) -> dict:
        """Moving does not touch Claims (section 4.3)."""
        if actor.kind not in AGENT_TENET_WRITERS:
            raise forbid(f"{actor.kind} can't move Tenets")
        with self.lock:
            tenets = self.tenets()
            t = tenets.get(tid) or self.tenet(tid)
            if new_parent not in tenets:
                raise HTTPException(404, f"No Tenet {new_parent}")
            if not t.get("parent_id"):
                raise conflict("The root Tenet can't be moved")
            if new_parent == tid or new_parent in self.descendants(tenets, tid):
                raise conflict("A Tenet can't move under itself")
            if tenets[new_parent]["code_links"]:
                raise conflict(f"{new_parent} is a leaf with code links. Clear its links first.")
            old = tenets[t["parent_id"]]
            old["children"].remove(tid)
            tenets[new_parent]["children"].append(tid)
            t["parent_id"] = new_parent
            if self._has_cycle(self._composition_edges(tenets)):
                raise conflict("That would create a reference cycle")
            for x in (t, old, tenets[new_parent]):
                self._save_tenet(x)
            self._write_indexes()
        self._emit("tenet.moved", tenet_id=tid, parent_id=new_parent)
        return t

    def delete_tenet(self, actor: Actor, tid: str) -> None:
        if actor.kind not in AGENT_TENET_WRITERS:
            raise forbid(f"{actor.kind} can't delete Tenets")
        with self.lock:
            tenets, claims = self.tenets(), self.claims()
            t = tenets.get(tid) or self.tenet(tid)
            axioms = self._holds_axioms(tid, claims)
            if axioms:
                raise conflict("This Tenet holds Axioms. Demote them before deleting it.", axioms=axioms)
            if t["children"]:
                raise conflict("Move or delete this Tenet's children first", children=t["children"])
            refs = self.referencers(tenets, tid)
            if refs:
                raise conflict("Other Tenets reference this one; remove those references first", referenced_by=refs)
            own = set(t["claims"])
            outside = [c["id"] for c in claims.values() if c["id"] not in own and own & set(c["dependencies"])]
            if outside:
                raise conflict("Claims elsewhere depend on this Tenet's Claims", dependents=outside)
            for cid in t["claims"]:
                c = self._read(self._path("claims", tid, f"{cid}.json"))
                if c:
                    self._history("scrapped", {**c, "scrap_reason": f"Tenet {tid} deleted by {actor.name}"})
            if t.get("parent_id"):
                parent = tenets[t["parent_id"]]
                parent["children"].remove(tid)
                self._save_tenet(parent)
            for f in self._path("claims", tid).glob("*.json"):
                f.unlink()
            self._path("tenets", f"{tid}.json").unlink()
            self._write_indexes()
        self._emit("tenet.deleted", tenet_id=tid)

    def add_reference(self, actor: Actor, tid: str, target: str) -> dict:
        if actor.kind not in AGENT_TENET_WRITERS:
            raise forbid(f"{actor.kind} can't add references")
        with self.lock:
            tenets = self.tenets()
            t = tenets.get(tid) or self.tenet(tid)
            if target not in tenets:
                raise HTTPException(404, f"No Tenet {target}")
            if target == tid or target in self.descendants(tenets, tid):
                raise conflict("A Tenet already owns its own subtree; references are for Tenets owned elsewhere")
            if target in self.ancestors(tenets, tid):
                raise conflict("Referencing an ancestor would create a cycle")
            if settings.reference_scope == "peer_children":
                peers = set(tenets[t["parent_id"]]["children"]) - {tid} if t.get("parent_id") else set()
                if tenets[target].get("parent_id") not in peers:
                    raise conflict("References may only target children of a peer Tenet (REFERENCE_SCOPE=peer_children)")
            if target not in t["references"]:
                t["references"].append(target)
            if self._has_cycle(self._composition_edges(tenets)):
                raise conflict("That would create a reference cycle")
            self._save_tenet(t)
            self._write_indexes()
        self._emit("tenet.updated", tenet_id=tid)
        return t

    def remove_reference(self, actor: Actor, tid: str, target: str) -> dict:
        if actor.kind not in AGENT_TENET_WRITERS:
            raise forbid(f"{actor.kind} can't remove references")
        with self.lock:
            t = self.tenet(tid)
            if target in t["references"]:
                t["references"].remove(target)
                self._save_tenet(t)
                self._write_indexes()
        self._emit("tenet.updated", tenet_id=tid)
        return t

    def set_links(self, actor: Actor, tid: str, links: List[dict]) -> dict:
        """Links are engine-generated (section 7); only leaves carry them (section 4.1)."""
        if actor.kind != "engine":
            raise forbid("Only the engine writes code links")
        for link in links:
            safe_repo_path(link["path"])
        with self.lock:
            t = self.tenet(tid)
            if t["children"] and links:
                raise conflict("Only leaf Tenets carry code links; this one has children")
            t["code_links"] = links
            self._save_tenet(t)
            self._write_indexes()
        self._emit("links.updated", tenet_id=tid)
        return t

    # ------------------------------------------------------------------ Claims

    def _check_dependencies(self, cid: str, deps: List[str], claims: Dict[str, dict]) -> None:
        for d in deps:
            if d == cid:
                raise HTTPException(422, "A Claim can't depend on itself")
            if d not in claims:
                raise HTTPException(422, f"Dependency {d} is not a live Claim")
        edges = {c["id"]: set(c["dependencies"]) for c in claims.values()}
        edges[cid] = set(deps)
        if self._has_cycle(edges):
            raise conflict("Those dependencies would create a cycle")

    def create_claim(self, actor: Actor, tid: str, data: dict, remade_from: Optional[str] = None) -> dict:
        if actor.kind not in HYPOTHESIS_WRITERS:
            raise forbid(f"{actor.kind} can't create Claims")
        with self.lock:
            tenet, claims = self.tenet(tid), self.claims()
            cid = new_id("c")
            self._check_dependencies(cid, data["dependencies"], claims)
            prov = data.get("provenance") or {}
            c = {
                "id": cid, "tenet_id": tid, "status": HYPOTHESIS,
                "provenance": actor.provenance(prov), "confidence": data["confidence"],
                "proposed": prov.get("via") == "sync",
                "verification": None, "flags": [], "version": 1, "remade_from": remade_from,
                "statement": data["statement"], "test_explanation": data["test_explanation"],
                "test_implementation": data["test_implementation"], "dependencies": data["dependencies"],
                "created_at": _now(),
            }
            self._save_claim(c)
            tenet["claims"].append(cid)
            self._save_tenet(tenet)
            self._write_indexes()
        self._emit("claim.created", claim_id=cid, tenet_id=tid)
        return c

    def update_hypothesis(self, actor: Actor, cid: str, fields: dict) -> dict:
        if actor.kind not in HYPOTHESIS_WRITERS:
            raise forbid(f"{actor.kind} can't edit Claims")
        with self.lock:
            c = self.claim(cid)
            if c["status"] == AXIOM:
                if actor.is_user:
                    raise conflict("This is an Axiom. Edit it by hand through the Axiom edit flow (with its warning), "
                                   "or demote it first.", code="AXIOM_LOCKED")
                raise forbid("Agents never edit Axioms. The user must demote it first.", code="AXIOM_LOCKED")
            if c["status"] == SCRAPPED:
                raise conflict("This Claim was scrapped; remake it instead")
            if fields.get("dependencies") is not None:
                self._check_dependencies(cid, fields["dependencies"], self.claims())
            for key in ("statement", "test_explanation", "test_implementation", "dependencies", "confidence"):
                if fields.get(key) is not None:
                    c[key] = fields[key]
            c["version"] += 1
            if actor.is_user:
                c["proposed"] = False
            self._save_claim(c)
            self._write_indexes()
        self._emit("claim.updated", claim_id=cid)
        return c

    def impact(self, cid: str) -> dict:
        """What demoting or hand-editing this Claim would touch (rule 12, section 11.5)."""
        tenets, claims = self.tenets(), self.claims()
        c = claims.get(cid) or self.claim(cid)
        dependents = self.dependents(cid, claims)
        up = self.upward(tenets, c["tenet_id"])
        integration = [x for x in claims.values() if x["tenet_id"] in up and x["id"] not in dependents]
        stale = [d for d in dependents if self.result_file(d)["runs"]]
        if self.result_file(cid)["runs"]:
            stale.insert(0, cid)
        spec_sections = sorted({c["tenet_id"]} | {t for t in up if self._holds_axioms(t, claims)})
        return {
            "claim_id": cid,
            "status": c["status"],
            "dependent_claims": [{"id": d, "tenet_id": claims[d]["tenet_id"], "status": claims[d]["status"],
                                  "statement": claims[d]["statement"]} for d in dependents],
            "integration_claims_above": [{"id": x["id"], "tenet_id": x["tenet_id"], "status": x["status"]}
                                         for x in integration],
            "referencing_tenets": self.referencers(tenets, c["tenet_id"]),
            "affected_tenets": sorted(up),
            "linked_code": self.footprint(tenets, c["tenet_id"]),
            "results_going_stale": stale,
            "spec_sections_provisional": spec_sections,
        }

    def edit_axiom(self, actor: Actor, cid: str, fields: dict, acknowledged: bool, reason: str) -> dict:
        """Direct user edit of an Axiom (section 11.8). No agent can reach this."""
        if not actor.is_user:
            raise forbid("Only a user can edit an Axiom, by hand")
        if not acknowledged:
            raise HTTPException(428, {"message": "Editing an Axiom needs acknowledge_warning=true", "impact": self.impact(cid)})
        if not reason.strip():
            raise HTTPException(422, "Give a reason for editing this Axiom")
        with self.lock:
            claims = self.claims()
            c = claims.get(cid) or self.claim(cid)
            if c["status"] != AXIOM:
                raise conflict("Not an Axiom; edit it as a Hypothesis")
            if fields.get("dependencies") is not None:
                self._check_dependencies(cid, fields["dependencies"], claims)
            self._history("axiom_versions", {**c, "snapshot_reason": f"hand edit: {reason}", "by": actor.name})
            for key in ("statement", "test_explanation", "test_implementation", "dependencies", "confidence"):
                if fields.get(key) is not None:
                    c[key] = fields[key]
            c["version"] += 1
            c["verification"] = "unverified_edit"
            self._save_claim(c)
            for d in self.dependents(cid, self.claims(), transitive=False):
                self._flag(d, "changed_base", f"{cid} was edited by hand: {reason}")
            self._invalidate_results(self.dependents(cid, self.claims()), f"{cid} edited")
            self._write_indexes()
            self.changelog({"type": "axiom_edit", "claim_id": cid, "by": actor.name, "reason": reason})
        self._emit("claim.updated", claim_id=cid)
        return c

    def _flag(self, cid: str, kind: str, detail: str) -> None:
        c = self.claim(cid)
        c["flags"].append({"kind": kind, "detail": detail, "at": _now()})
        self._write(self._path("claims", c["tenet_id"], f"{cid}.json"), c)
        # Always surfaced to the user (chat contract 5, spec 11.6): nothing changes automatically.
        self._emit("flag.raised", claim_id=cid, tenet_id=c["tenet_id"], status=c["status"],
                   kind=kind, reason=detail)

    def clear_flag(self, actor: Actor, cid: str, kind: str) -> dict:
        if not actor.is_user:
            raise forbid("Only a user can dismiss flags")
        with self.lock:
            c = self.claim(cid)
            c["flags"] = [f for f in c["flags"] if f["kind"] != kind]
            self._write(self._path("claims", c["tenet_id"], f"{cid}.json"), c)
        self._emit("claim.updated", claim_id=cid)
        return c

    def promote(self, actor: Actor, cid: str, accept_without_verification: bool) -> dict:
        """Hypothesis -> Axiom, user only, with the verification gate (rules 2, 7, 8)."""
        if not actor.is_user:
            raise forbid("Only the user changes a Claim's status")
        with self.lock:
            claims = self.claims()
            c = claims.get(cid) or self.claim(cid)
            if c["status"] != HYPOTHESIS:
                raise conflict(f"Only Hypotheses can be promoted; this one is {c['status']}")
            unmet = [d for d in c["dependencies"]
                     if claims[d]["status"] != AXIOM and self.summarize_result(claims[d])["verdict"] != "pass"]
            if unmet:
                raise conflict("Promotion is bottom-up: lock or pass these dependencies first",
                               code="DEPENDENCY_NOT_READY", unmet=unmet, blockers=unmet)
            result = self.summarize_result(c)
            verified = result["verdict"] == "pass" and not result["flaky"]
            if not verified and not accept_without_verification:
                raise conflict(
                    "Promotion needs a passing, non-flaky result for the current wording, "
                    "or accept_without_verification=true",
                    code="NOT_VERIFIED",
                    result=result,
                )
            previous = [h for h in self.history("axiom_versions") if h["id"] == cid]
            c["status"] = AXIOM
            c["verification"] = "verified" if verified else "accepted_without_verification"
            c["proposed"] = False
            c["flags"] = [f for f in c["flags"] if f["kind"] not in ("unlocked_base",)]
            self._save_claim(c)
            self._history("axiom_versions", {**c, "snapshot_reason": "promoted", "by": actor.name})
            self.changelog({"type": "promote", "claim_id": cid, "by": actor.name,
                            "verification": c["verification"]})
            stabilized = self.dependents(cid, self.claims())
        self._emit("claim.status", claim_id=cid, status=AXIOM)
        return {
            **c,
            "previous_axiom": previous[-1] if previous else None,
            "dependents_stabilized": len(stabilized),
        }

    def demote(self, actor: Actor, cid: str, reason: str) -> dict:
        """Axiom -> Hypothesis, user only; snapshot, flag dependents, stale their results (11.5)."""
        if not actor.is_user:
            raise forbid("Only the user changes a Claim's status")
        with self.lock:
            impact = self.impact(cid)
            c = self.claim(cid)
            if c["status"] != AXIOM:
                raise conflict("Only Axioms can be demoted")
            self._history("axiom_versions", {**c, "snapshot_reason": f"demoted: {reason}", "by": actor.name})
            c["status"] = HYPOTHESIS
            c["verification"] = None
            self._save_claim(c)
            for d in self.dependents(cid, self.claims(), transitive=False):
                self._flag(d, "unlocked_base", f"Depends on {cid}, demoted: {reason}")
            self._invalidate_results([d["id"] for d in impact["dependent_claims"]], f"{cid} demoted")
            self.changelog({"type": "demote", "claim_id": cid, "by": actor.name, "reason": reason})
        self._emit("claim.status", claim_id=cid, status=HYPOTHESIS)
        return {**c, "impact": impact}

    def scrap(self, actor: Actor, cid: str, reason: str, rejected: Optional[str]) -> dict:
        if actor.kind not in ("user", "builder"):
            raise forbid(f"{actor.kind} can't scrap Claims")
        with self.lock:
            claims = self.claims()
            c = claims.get(cid) or self.claim(cid)
            if c["status"] == AXIOM:
                raise conflict("Axioms are never scrapped directly. Demote it first.", code="AXIOM_LOCKED")
            if c["status"] == SCRAPPED:
                raise conflict("Already scrapped")
            c["status"] = SCRAPPED
            c["scrap_reason"] = reason
            self._save_claim(c)
            self._history("scrapped", {**c, "by": actor.name})
            self._history("rejected", {"id": cid, "tenet_id": c["tenet_id"],
                                       "interpretation": rejected or c["statement"], "reason": reason})
            for d in self.dependents(cid, claims, transitive=False):
                self._flag(d, "scrapped_dependency", f"Depends on {cid}, scrapped: {reason}")
            self.changelog({"type": "scrap", "claim_id": cid, "by": actor.name, "reason": reason})
        self._emit("claim.status", claim_id=cid, status=SCRAPPED)
        return c

    def rejected_interpretations(self, tid: str) -> List[dict]:
        return [h for h in self.history("rejected") if h["tenet_id"] == tid]

    def remake(self, actor: Actor, scrapped_id: str, data: dict) -> dict:
        """Scrapped -> new Hypothesis on the same Tenet; must differ from rejected readings."""
        if actor.kind not in ("user", "builder"):
            raise forbid(f"{actor.kind} can't remake Claims")
        old = self.claim(scrapped_id)
        if old["status"] != SCRAPPED:
            raise conflict("Only scrapped Claims can be remade")
        rejected = {r["interpretation"].strip().lower() for r in self.rejected_interpretations(old["tenet_id"])}
        if data["statement"].strip().lower() in rejected:
            raise conflict("This statement repeats a rejected interpretation")
        data = {**data, "provenance": {**(data.get("provenance") or {}), "via": "remake"}}
        return self.create_claim(actor, old["tenet_id"], data, remade_from=scrapped_id)

    def append_result(self, actor: Actor, cid: str, run: dict) -> dict:
        """Test Runner only, append-only (rules 3, 4, 5, 6)."""
        if actor.kind != "test_runner":
            raise forbid("Only the Test Runner writes results")
        if run.get("underspecified") and run["verdict"] != "inconclusive":
            raise HTTPException(422, "An underspecified recipe must be reported as inconclusive")
        with self.lock:
            c = self.claim(cid)
            if c["status"] == SCRAPPED:
                raise conflict("This Claim was scrapped")
            if run["claim_hash"] != c["content_hash"]:
                raise conflict("This run tested an older wording of the Claim (hash mismatch)",
                               current_hash=c["content_hash"])
            rf = self.result_file(cid)
            rf["tenet_id"] = c["tenet_id"]
            rf["runs"].append({**run, "at": _now(), "runner": actor.name})
            self._write(self._path("results", f"{cid}.json"), rf)
            summary = self.summarize_result(c, rf)
            if c["status"] == AXIOM:
                if run["verdict"] == "fail":
                    # Rule 4: a flag, never a change.
                    self._flag(cid, "test_failure", run.get("notes") or "Axiom test failed")
                elif run["verdict"] == "pass" and not summary["flaky"] and c["verification"] != "verified":
                    c = self.claim(cid)
                    c["verification"] = "verified"
                    self._write(self._path("claims", c["tenet_id"], f"{cid}.json"), c)
        self._emit("result.appended", claim_id=cid, verdict=run["verdict"], summary=summary)
        return summary

    # ------------------------------------------------------------------ engine outputs

    def _annotation_path(self, path: str) -> Path:
        return self._path("annotations", safe_repo_path(path) + ".json")

    def put_annotation(self, actor: Actor, path: str, data: dict) -> dict:
        if actor.kind != "engine":
            raise forbid("Only the engine writes annotations")
        record = {"path": path, **data, "updated_at": _now()}
        with self.lock:
            self._write(self._annotation_path(path), record)
        self._emit("annotation.updated", path=path)
        return record

    def get_annotation(self, path: str) -> Optional[dict]:
        return self._read(self._annotation_path(path))

    def annotated_paths(self) -> Set[str]:
        base = self._path("annotations")
        return {str(f.relative_to(base))[: -len(".json")] for f in base.rglob("*.json")}

    def apply_renames(self, renames: Dict[str, str]) -> None:
        """Carry annotations and code links across git renames (section 9)."""
        if not renames:
            return
        with self.lock:
            for old, new in renames.items():
                src = self._annotation_path(old)
                if src.exists():
                    record = json.loads(src.read_text())
                    record["path"] = new
                    self._write(self._annotation_path(new), record)
                    src.unlink()
            for t in self.tenets().values():
                changed = False
                for link in t["code_links"]:
                    if link["path"] in renames:
                        link["path"] = renames[link["path"]]
                        changed = True
                if changed:
                    self._save_tenet(t)
            self._write_indexes()

    def put_imports(self, snapshot: dict) -> None:
        with self.lock:
            self._write(self._path("links", "imports.json"), snapshot)

    def imports(self) -> Optional[dict]:
        return self._read(self._path("links", "imports.json"))

    def put_spec(self, actor: Actor, markdown: str, sections: List[dict]) -> dict:
        if actor.kind != "engine":
            raise forbid("Only the Spec Compiler writes the spec")
        record = {"markdown": markdown, "sections": sections, "compiled_at": _now()}
        with self.lock:
            self._write(self._path("spec", "spec.json"), record)
            self._path("spec", "spec.md").write_text(markdown)
        self._emit("spec.updated")
        return record

    def spec(self) -> Optional[dict]:
        return self._read(self._path("spec", "spec.json"))

    def record_jev(self, actor: Actor, verdict: dict) -> dict:
        """Validate Jev's typed output against the tree (section 10.6) and act on it (section 12)."""
        if actor.kind != "engine":
            raise forbid("Only the engine (Jev) records change verdicts")
        with self.lock:
            tenets, claims = self.tenets(), self.claims()
            missing = [t for t in verdict["affected_tenets"] if t not in tenets] + \
                      [c for c in verdict["affected_claims"] if c not in claims]
            if missing:
                raise HTTPException(422, {"message": "Verdict names ids that don't exist", "missing": missing})
            axioms = [c for c in verdict["affected_claims"] if claims[c]["status"] == AXIOM]
            if verdict["verdict"] == "update_existing" and axioms:
                raise HTTPException(422, {"message": "Jev may only route changes to Hypotheses; "
                                                     "a change to an Axiom is an axiom_conflict", "axioms": axioms})
            if verdict["verdict"] == "axiom_conflict":
                if not axioms:
                    raise HTTPException(422, "axiom_conflict must name at least one Axiom")
                for cid in axioms:
                    self._flag(cid, "jev_conflict", verdict["reason"])
            entry = {"type": "jev", "by": actor.name, **verdict,
                     "to_review_inbox": verdict["confidence"] == "low"}
            self.changelog(entry)
        self._emit("jev.verdict", **verdict)
        return entry
