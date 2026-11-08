from typing import Dict, Type
from app.copilot.core.interfaces import BaseTestRunner
from app.copilot.services.testing.pytest_runner import PytestRunner

class TestRunnerFactory:
    """
    Factory pattern for Test Execution Harnesses.
    Allows plugging in Pytest, Jest, or custom test harnesses.
    """
    _registry: Dict[str, Type[BaseTestRunner]] = {
        "pytest": PytestRunner,
    }
    _instances: Dict[str, BaseTestRunner] = {}

    @classmethod
    def register(cls, framework: str, runner_cls: Type[BaseTestRunner]) -> None:
        cls._registry[framework.lower()] = runner_cls

    @classmethod
    def get_runner(cls, framework: str = "pytest") -> BaseTestRunner:
        name = framework.lower()
        if name not in cls._instances:
            runner_cls = cls._registry.get(name, PytestRunner)
            cls._instances[name] = runner_cls()
        return cls._instances[name]

# Default global runner
default_test_runner = TestRunnerFactory.get_runner("pytest")

