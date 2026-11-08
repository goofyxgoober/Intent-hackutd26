"""
Backward-compatibility alias. Points to modular implementation in app.services.testing.factory.
"""
from app.copilot.services.testing.factory import default_test_runner as test_runner_service
from app.copilot.services.testing.pytest_runner import PytestRunner as TestRunnerService
