"""Test Runner agent: sandboxed test execution, determinism checks, and bottom-up topological execution."""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..engine import IntentEngine
from ..llm import Nemotron
from ..models import (
    Actor,
    Claim,
    EngineError,
    Status,
    Tenet,
    TestRunRecord,
    Verdict,
)
from ..store import Store


class SubprocessSandbox:
    """Copies REPO_PATH to a temporary workspace and executes test recipes safely (Rule 13)."""

    def __init__(self, repo_path: Path | str, timeout: int = 30):
        self.repo_path = Path(repo_path).resolve()
        self.timeout = timeout

    def run(self, cmd: str) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy repository to temporary directory
            dest = Path(tmpdir) / "repo"
            if self.repo_path.exists():
                shutil.copytree(
                    self.repo_path,
                    dest,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", "node_modules", "data"),
                )
            else:
                dest.mkdir(parents=True)

            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(dest),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                return {
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[:8000],
                    "stderr": proc.stderr[:8000],
                }
            except subprocess.TimeoutExpired:
                return {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Execution timed out after {self.timeout}s",
                }
            except Exception as e:
                return {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                }


class TestRunner:
    __test__ = False
    def __init__(
        self,
        engine: IntentEngine,
        store: Store,
        repo_path: Path | str,
        sandbox: Optional[SubprocessSandbox] = None,
        llm: Optional[Nemotron] = None,
    ):
        self.engine = engine
        self.store = store
        self.repo_path = Path(repo_path).resolve()
        self.sandbox = sandbox or SubprocessSandbox(self.repo_path)
        self.llm = llm or Nemotron()

    def run_claim_test(
        self,
        claim_id: str,
        code_ref: Optional[str] = None,
        forced_verdict: Optional[Verdict] = None,
    ) -> TestRunRecord:
        """Executes a single Claim's test recipe in sandbox with determinism check (Rule 5 & 10.4)."""
        c = self.store.get_claim(claim_id)
        recipe = c.test_impl

        # Check if recipe is missing or underspecified
        if not recipe or len(recipe.strip()) < 10:
            rec = TestRunRecord(
                claim_hash=c.content_hash(),
                verdict=Verdict.INCONCLUSIVE,
                notes="spec underspecified: test recipe is empty or incomplete",
                underspecified="Missing test implementation recipe",
            )
            self.store.append_result(c.id, rec, Actor.TEST_RUNNER)
            return rec

        if forced_verdict is not None:
            rec = TestRunRecord(
                claim_hash=c.content_hash(),
                verdict=forced_verdict,
                invoked="simulated",
                actual="simulated output",
                expected="pass criteria",
                code_ref=code_ref,
            )
            self.store.append_result(c.id, rec, Actor.TEST_RUNNER)
            self._handle_verdict_side_effects(c, rec.verdict, rec.notes)
            return rec

        # Determinism check for first execution: run twice
        is_first_run = not self.store.has_results(c.id)

        # Parse and execute recipe command (look for python command or pytest or inline check)
        cmd = "python3 -c 'exit(0)'"
        if "INVOKE:" in recipe:
            invoke_part = recipe.split("INVOKE:")[1].split("ASSERT:")[0].strip()
            if invoke_part:
                cmd = f"python3 -c '{invoke_part}'" if not invoke_part.startswith("python") else invoke_part

        res1 = self.sandbox.run(cmd)
        verdict1 = Verdict.PASS if res1["exit_code"] == 0 else Verdict.FAIL

        rec1 = TestRunRecord(
            claim_hash=c.content_hash(),
            verdict=verdict1,
            invoked=cmd,
            actual=res1["stdout"] or res1["stderr"],
            expected="exit 0",
            code_ref=code_ref,
        )

        if is_first_run:
            # Second run for determinism check
            res2 = self.sandbox.run(cmd)
            verdict2 = Verdict.PASS if res2["exit_code"] == 0 else Verdict.FAIL
            if verdict1 != verdict2:
                rec1.flaky = True
                rec1.verdict = Verdict.INCONCLUSIVE
                rec1.notes = "Determinism check failed: test produced conflicting verdicts across runs"

        self.store.append_result(c.id, rec1, Actor.TEST_RUNNER)
        self._handle_verdict_side_effects(c, rec1.verdict, rec1.notes)
        return rec1

    def _handle_verdict_side_effects(self, c: Claim, verdict: Verdict, notes: str) -> None:
        """Handle Rule 4 and confidence updates."""
        if c.status == Status.AXIOM:
            if verdict == Verdict.FAIL:
                self.engine.handle_test_verdict(c.id, Verdict.FAIL, notes)
            elif verdict == Verdict.PASS:
                self.engine.handle_test_verdict(c.id, Verdict.PASS, notes)
        elif c.status == Status.HYPOTHESIS:
            if verdict == Verdict.PASS:
                self.store.set_confidence(c.id, min(1.0, c.confidence + 0.2))
            elif verdict == Verdict.FAIL:
                self.store.set_confidence(c.id, max(0.05, c.confidence - 0.2))

    def run_tests_bottom_up(
        self,
        tenet_id: Optional[str] = None,
        subtree: bool = True,
        forced_verdicts: Optional[Dict[str, Verdict]] = None,
    ) -> List[TestRunRecord]:
        """Runs tests bottom-up: leaves first, then integration claims (spec 11.3 & 11.4)."""
        forced_verdicts = forced_verdicts or {}
        all_tenets = {t.id: t for t in self.store.all_tenets()}
        target_tenets: Set[str] = set()

        if tenet_id:
            if subtree:
                target_tenets = self.engine._subtree(tenet_id)
            else:
                target_tenets = {tenet_id}
        else:
            target_tenets = set(all_tenets.keys())

        # Group claims by dependency depth
        claims = [c for c in self.store.all_claims() if c.tenet_id in target_tenets]

        # Topological sort of claims
        sorted_claims: List[Claim] = []
        visited: Set[str] = set()

        def visit(c: Claim):
            if c.id in visited:
                return
            visited.add(c.id)
            for did in c.dependencies:
                dep_claim = self.store.find_claim(did)
                if dep_claim and dep_claim.id not in visited:
                    visit(dep_claim)
            sorted_claims.append(c)

        for c in claims:
            visit(c)

        records: List[TestRunRecord] = []
        for c in sorted_claims:
            # Check dependencies
            blocked = False
            for did in c.dependencies:
                dep = self.store.find_claim(did)
                if dep and self.store.latest_verdict(dep) == Verdict.FAIL:
                    blocked = True
                    rec = TestRunRecord(
                        claim_hash=c.content_hash(),
                        verdict=Verdict.INCONCLUSIVE,
                        notes=f"Blocked by child failure on claim {did}",
                        localized="child_failure",
                    )
                    self.store.append_result(c.id, rec, Actor.TEST_RUNNER)
                    records.append(rec)
                    break

            if blocked:
                continue

            fv = forced_verdicts.get(c.id)
            rec = self.run_claim_test(c.id, forced_verdict=fv)

            # Failure localization (spec 11.4): if all children pass and integration claim fails
            if rec.verdict == Verdict.FAIL and c.dependencies:
                all_deps_pass = all(
                    self.store.latest_verdict(self.store.get_claim(did)) == Verdict.PASS
                    for did in c.dependencies
                    if self.store.find_claim(did)
                )
                if all_deps_pass:
                    rec.localized = "composition"
                    rec.notes += " [localized: composition failure; children passed]"

            records.append(rec)

        return records
