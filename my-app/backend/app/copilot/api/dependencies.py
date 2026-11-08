from typing import Optional
from fastapi import Query
from app.copilot.core.interfaces import BaseGraphStore, BaseLLMAgent, BaseTestRunner
from app.copilot.services.graph.factory import GraphStoreFactory
from app.copilot.services.llm.factory import AgentFactory
from app.copilot.services.testing.factory import TestRunnerFactory

def get_graph_store() -> BaseGraphStore:
    """Dependency injection provider for Graph Engine."""
    return GraphStoreFactory.get_store("memory")

def get_agent(
    provider: Optional[str] = Query(None, description="Optional LLM provider: 'gemini' or 'nemotron'")
) -> BaseLLMAgent:
    """Dependency injection provider for LLM Modernization Agent."""
    return AgentFactory.get_agent(provider=provider)

def get_test_runner(
    framework: str = Query("pytest", description="Test framework: 'pytest'")
) -> BaseTestRunner:
    """Dependency injection provider for Invariant Test Runner."""
    return TestRunnerFactory.get_runner(framework)

