import os
import sys
import tempfile
import time
import subprocess
import re
from typing import Dict, List, Optional, Any
from app.copilot.core.interfaces import BaseTestRunner, BaseGraphStore, BaseLLMAgent
from app.copilot.services.graph.factory import GraphStoreFactory
from app.copilot.services.llm.factory import AgentFactory

class PytestRunner(BaseTestRunner):
    """
    Automated Invariant Verification Runner using Pytest.
    Adheres strictly to BaseTestRunner for plug-and-play test harness swapping.
    """

    def __init__(
        self,
        graph_store: Optional[BaseGraphStore] = None,
        agent: Optional[BaseLLMAgent] = None
    ):
        self.graph_store = graph_store or GraphStoreFactory.get_store()
        self.agent = agent or AgentFactory.get_agent()

    async def run_invariant_tests(
        self,
        node_id: str,
        custom_test_code: Optional[str] = None
    ) -> Dict[str, Any]:
        start_time = time.time()
        node = self.graph_store.get_node(node_id)
        if not node:
            return {
                "node_id": node_id,
                "status": "ERROR",
                "error": f"IntentNode '{node_id}' not found in Intent Graph."
            }

        test_code = custom_test_code
        if not test_code:
            test_resp = await self.agent.generate_deterministic_test_suite(node_id, framework="pytest")
            test_code = test_resp.test_code

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file_path = os.path.join(tmp_dir, f"test_{node_id}.py")
            with open(test_file_path, "w", encoding="utf-8") as f:
                f.write(test_code)

            cmd = [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            stdout = result.stdout
            stderr = result.stderr
            returncode = result.returncode

        test_items = []
        for line in stdout.splitlines():
            match = re.search(r"::(test_\w+)\s+(PASSED|FAILED|ERROR)", line)
            if match:
                test_name = match.group(1)
                status = match.group(2)
                test_items.append({
                    "test_name": test_name,
                    "status": status,
                    "target_invariant": self._find_matching_invariant(test_name, node.business_invariants)
                })

        passed_count = sum(1 for t in test_items if t["status"] == "PASSED")
        failed_count = sum(1 for t in test_items if t["status"] == "FAILED")
        total_count = len(test_items)
        pass_rate = f"{round((passed_count / max(1, total_count)) * 100, 1)}%" if total_count > 0 else "100%"

        return {
            "node_id": node_id,
            "node_name": node.name,
            "overall_status": "PASSED" if returncode == 0 else "FAILED",
            "total_invariants_tested": len(node.business_invariants),
            "total_tests_run": total_count,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": pass_rate,
            "execution_time_ms": elapsed_ms,
            "test_results": test_items,
            "raw_output": stdout if stdout else stderr
        }

    def _find_matching_invariant(self, test_name: str, invariants: List[str]) -> str:
        match = re.search(r"invariant_(\d+)", test_name)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(invariants):
                return invariants[idx]
        return "Core Functional Contract Invariant"

