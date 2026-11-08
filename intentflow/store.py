"""Filesystem store enforcing the Intent Spec permissions and non-negotiable rules."""
import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .models import (
    Actor,
    Claim,
    CodeLink,
    EngineError,
    PendingConfirmation,
    PermissionDenied,
    ResultFile,
    Status,
    Tenet,
    TestRunRecord,
    Verdict,
    new_id,
)

_locks: Dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _get_lock(path_key: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(path_key, threading.RLock())


class Store:
    """Store for an intent directory adhering to section 6 and permission matrix section 7."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.lock = _get_lock(str(self.root))
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for sub in [
            "tenets",
            "claims",
            "results",
            "annotations",
            "links",
            "history",
            "spec",
            "changelog",
            ".pending",
            ".sessions",
        ]:
            self.root.joinpath(sub).mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}")
        if isinstance(data, (dict, list)):
            tmp.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")
        elif isinstance(data, str):
            tmp.write_text(data, encoding="utf-8")
        else:
            tmp.write_text(json.dumps(data.model_dump(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _read_json(self, path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    # ------------------------------------------------------------------ Claims

    def all_claims(self, include_scrapped: bool = False) -> List[Claim]:
        with self.lock:
            out = []
            claims_dir = self.root / "claims"
            for f in claims_dir.glob("*/*.json"):
                data = self._read_json(f)
                if data:
                    c = Claim.model_validate(data)
                    if include_scrapped or c.status != Status.SCRAPPED:
                        out.append(c)
            return out

    def get_claim(self, claim_id: str) -> Claim:
        with self.lock:
            claims_dir = self.root / "claims"
            matches = list(claims_dir.glob(f"*/{claim_id}.json"))
            if not matches:
                raise EngineError("NOT_FOUND", f"Claim {claim_id} not found")
            return Claim.model_validate(self._read_json(matches[0]))

    def find_claim(self, claim_id: str) -> Optional[Claim]:
        try:
            return self.get_claim(claim_id)
        except EngineError:
            return None

    def put_claim(self, claim: Claim, actor: Actor) -> Claim:
        """Enforces Rule 1, 2, 3, 10 on Claims."""
        with self.lock:
            existing = self.find_claim(claim.id)
            if existing is not None:
                # Rule 1: Axioms are never edited by an LLM / agent.
                if existing.status == Status.AXIOM and actor != Actor.USER:
                    raise PermissionDenied(f"Axiom {claim.id} is locked; agents cannot edit it")
                # Rule 2: Only the user changes status to Axiom or demotes Axiom
                if existing.status != claim.status and actor != Actor.USER:
                    raise PermissionDenied(
                        f"Actor '{actor.value}' cannot change Claim status from {existing.status.value} to {claim.status.value}"
                    )
            else:
                # New claim
                if claim.status == Status.AXIOM and actor != Actor.USER:
                    raise PermissionDenied("Only the user can create or promote an Axiom")
                if actor == Actor.TEST_RUNNER:
                    raise PermissionDenied("Test runner cannot create claims")

            # Check owning tenet exists
            tenet_path = self.root / "tenets" / f"{claim.tenet_id}.json"
            if not tenet_path.exists():
                raise EngineError("VALIDATION", f"Owning tenet {claim.tenet_id} does not exist")

            claim_path = self.root / "claims" / claim.tenet_id / f"{claim.id}.json"
            self._atomic_write(claim_path, claim.model_dump())
            return claim

    def create_claim(
        self,
        tenet_id: str,
        statement: str,
        actor: Actor,
        status: Status = Status.HYPOTHESIS,
        test_explanation: str = "",
        test_impl: str = "",
        dependencies: Optional[List[str]] = None,
        confidence: float = 0.3,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> Claim:
        with self.lock:
            claim = Claim(
                id=new_id("c"),
                tenet_id=tenet_id,
                status=status,
                statement=statement,
                test_explanation=test_explanation,
                test_implementation=test_impl,
                dependencies=dependencies or [],
                confidence=confidence,
                provenance=provenance or {"actor": actor.value},
            )
            return self.put_claim(claim, actor)

    def engine_flag(
        self,
        claim_id: str,
        flagged: bool = True,
        flag_reason: Optional[str] = None,
        base_flag: Optional[str] = None,
    ) -> Claim:
        """System/Engine flag modification (e.g. failing Axiom test or unlocked base)."""
        with self.lock:
            c = self.get_claim(claim_id)
            c.flagged = flagged
            if flag_reason is not None:
                c.flag_reason = flag_reason
            if base_flag is not None:
                c.base_flag = base_flag
            claim_path = self.root / "claims" / c.tenet_id / f"{c.id}.json"
            self._atomic_write(claim_path, c.model_dump())
            return c

    def set_confidence(self, claim_id: str, confidence: float) -> Claim:
        with self.lock:
            c = self.get_claim(claim_id)
            c.confidence = max(0.0, min(1.0, confidence))
            claim_path = self.root / "claims" / c.tenet_id / f"{c.id}.json"
            self._atomic_write(claim_path, c.model_dump())
            return c

    # ------------------------------------------------------------------ Tenets

    def all_tenets(self) -> List[Tenet]:
        with self.lock:
            out = []
            for f in (self.root / "tenets").glob("*.json"):
                data = self._read_json(f)
                if data:
                    out.append(Tenet.model_validate(data))
            return out

    def get_tenet(self, tenet_id: str) -> Tenet:
        with self.lock:
            path = self.root / "tenets" / f"{tenet_id}.json"
            if not path.exists():
                raise EngineError("NOT_FOUND", f"Tenet {tenet_id} not found")
            return Tenet.model_validate(self._read_json(path))

    def find_tenet(self, tenet_id: str) -> Optional[Tenet]:
        try:
            return self.get_tenet(tenet_id)
        except EngineError:
            return None

    def put_tenet(self, tenet: Tenet, actor: Actor) -> Tenet:
        with self.lock:
            existing = self.find_tenet(tenet.id)
            if existing is not None and actor != Actor.USER:
                # Rule 10: Agents may not delete, merge, or split a Tenet that holds Axioms.
                # Agents may add children, references, and Hypotheses and edit functionality statement.
                tenet_axioms = [
                    c for c in self.all_claims()
                    if c.tenet_id == tenet.id and c.status == Status.AXIOM
                ]
                if tenet_axioms:
                    # Ensure agent did not remove children that own axioms
                    removed_children = set(existing.children) - set(tenet.children)
                    for child_id in removed_children:
                        child_axioms = [
                            c for c in self.all_claims()
                            if c.tenet_id == child_id and c.status == Status.AXIOM
                        ]
                        if child_axioms:
                            raise PermissionDenied(
                                f"Tenet {tenet.id} holds Axioms; agents cannot remove child {child_id}"
                            )

            path = self.root / "tenets" / f"{tenet.id}.json"
            self._atomic_write(path, tenet.model_dump())
            return tenet

    def delete_tenet(self, tenet_id: str, actor: Actor) -> None:
        """Enforces Rule 10: Tenets holding Axioms cannot be deleted by agents."""
        with self.lock:
            t = self.get_tenet(tenet_id)
            claims = self.all_claims()
            holds_axioms = [c for c in claims if c.tenet_id == tenet_id and c.status == Status.AXIOM]
            if holds_axioms and actor != Actor.USER:
                raise PermissionDenied(
                    f"Tenet {tenet_id} holds {len(holds_axioms)} Axioms and cannot be deleted by agents (Rule 10)"
                )

            # Check if any other tenet references this tenet
            for other in self.all_tenets():
                if tenet_id in other.references:
                    raise EngineError(
                        "CONFLICT",
                        f"Tenet {tenet_id} is referenced by {other.id} and cannot be deleted",
                    )
                if tenet_id in other.children:
                    other.children.remove(tenet_id)
                    self.put_tenet(other, actor)

            # Remove claims under this tenet
            claims_dir = self.root / "claims" / tenet_id
            if claims_dir.exists():
                shutil.rmtree(claims_dir, ignore_errors=True)

            # Remove tenet file
            path = self.root / "tenets" / f"{tenet_id}.json"
            if path.exists():
                path.unlink()

    # ------------------------------------------------------------------ Results

    def result_file(self, claim_id: str) -> ResultFile:
        with self.lock:
            path = self.root / "results" / f"{claim_id}.json"
            data = self._read_json(path)
            if data:
                return ResultFile.model_validate(data)
            c = self.find_claim(claim_id)
            tenet_id = c.tenet_id if c else ""
            return ResultFile(claim_id=claim_id, tenet_id=tenet_id, runs=[])

    def has_results(self, claim_id: str) -> bool:
        with self.lock:
            rf = self.result_file(claim_id)
            return len(rf.runs) > 0

    def append_result(self, claim_id: str, run: TestRunRecord, actor: Actor) -> ResultFile:
        """Append-only test run record. Determinism check marks flaky if conflicting results (Rule 5)."""
        with self.lock:
            rf = self.result_file(claim_id)
            # Determinism check: identical runs (same claim_hash + code_ref) with differing verdicts -> flaky
            identical_runs = [
                r for r in rf.runs
                if r.claim_hash == run.claim_hash and (r.code_ref == run.code_ref or run.code_ref is None)
            ]
            if identical_runs:
                prior_verdict = identical_runs[-1].verdict
                if prior_verdict != run.verdict and prior_verdict in (Verdict.PASS, Verdict.FAIL) and run.verdict in (Verdict.PASS, Verdict.FAIL):
                    run.flaky = True
                    for r in identical_runs:
                        r.flaky = True

            rf.runs.append(run)
            path = self.root / "results" / f"{claim_id}.json"
            self._atomic_write(path, rf.model_dump())
            return rf

    def latest_verdict(self, claim: Claim) -> Verdict:
        """Returns the latest verdict for a Claim, binding to its content_hash (Rule 6)."""
        with self.lock:
            rf = self.result_file(claim.id)
            if not rf.runs:
                return Verdict.NONE
            latest = rf.runs[-1]
            # Rule 6: Results are bound to the Claim they tested. Mismatch = stale.
            if latest.claim_hash != claim.content_hash():
                return Verdict.STALE
            # Flaky tests mark verdict as inconclusive (spec 5)
            if latest.flaky:
                return Verdict.INCONCLUSIVE
            return latest.verdict

    def mark_results_stale(self, claim_id: str) -> None:
        """Mark results for a claim as stale by appending a stale run or letting hash mismatch indicate it."""
        with self.lock:
            rf = self.result_file(claim_id)
            if rf.runs:
                rf.runs.append(
                    TestRunRecord(
                        claim_hash="stale_override",
                        verdict=Verdict.STALE,
                        notes="Marked stale due to dependency ripple or parent modification",
                    )
                )
                self._atomic_write(self.root / "results" / f"{claim_id}.json", rf.model_dump())

    # ------------------------------------------------------------------ Pending Confirmations

    def put_pending(self, data: Dict[str, Any]) -> PendingConfirmation:
        with self.lock:
            pc = PendingConfirmation.model_validate(data)
            path = self.root / ".pending" / f"{pc.id}.json"
            self._atomic_write(path, pc.model_dump())
            return pc

    def get_pending(self, pid: str) -> Optional[PendingConfirmation]:
        with self.lock:
            path = self.root / ".pending" / f"{pid}.json"
            data = self._read_json(path)
            return PendingConfirmation.model_validate(data) if data else None

    def del_pending(self, pid: str) -> None:
        with self.lock:
            path = self.root / ".pending" / f"{pid}.json"
            if path.exists():
                path.unlink()

    # ------------------------------------------------------------------ History & Snapshots

    def snapshot(self, kind: str, record: Dict[str, Any]) -> None:
        with self.lock:
            entry = {
                "kind": kind,
                "timestamp": time.time(),
                "record": record,
            }
            hist_dir = self.root / "history"
            hist_dir.mkdir(parents=True, exist_ok=True)
            with (hist_dir / "snapshots.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    def rejected_interpretations(self, tenet_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            path = self.root / "history" / "rejected_interpretations.jsonl"
            if not path.exists():
                return []
            out = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if item.get("tenet_id") == tenet_id:
                        out.append(item)
            return out

    def add_rejected_interpretation(self, tenet_id: str, text: str, reason: str = "") -> None:
        with self.lock:
            entry = {
                "tenet_id": tenet_id,
                "text": text,
                "reason": reason,
                "timestamp": time.time(),
            }
            path = self.root / "history" / "rejected_interpretations.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    # ------------------------------------------------------------------ Annotations & Spec

    def get_annotation(self, path: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            clean = path.strip("/").replace("/", "__")
            f = self.root / "annotations" / f"{clean}.json"
            return self._read_json(f)

    def put_annotation(self, path: str, data: Dict[str, Any], actor: Actor) -> None:
        with self.lock:
            clean = path.strip("/").replace("/", "__")
            f = self.root / "annotations" / f"{clean}.json"
            self._atomic_write(f, data)

    def spec(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            path = self.root / "spec" / "spec.json"
            return self._read_json(path)

    def put_spec(self, markdown: str, sections: List[Dict[str, Any]], actor: Actor) -> Dict[str, Any]:
        with self.lock:
            doc = {"markdown": markdown, "sections": sections, "updated_at": time.time()}
            self._atomic_write(self.root / "spec" / "spec.json", doc)
            self._atomic_write(self.root / "spec" / "spec.md", markdown)
            return doc

    # ------------------------------------------------------------------ Changelog

    def changelog(self, entry: Dict[str, Any]) -> None:
        with self.lock:
            entry["timestamp"] = entry.get("timestamp", time.time())
            path = self.root / "changelog" / "changelog.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    def read_changelog(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.lock:
            path = self.root / "changelog" / "changelog.jsonl"
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
            return [json.loads(line) for line in lines[-limit:] if line.strip()]
