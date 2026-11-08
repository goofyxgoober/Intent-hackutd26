import os
from typing import Dict, Type, Optional
from app.copilot.core.interfaces import BaseLLMAgent, BaseGraphStore
from app.copilot.services.llm.gemini_agent import GeminiAgent
from app.copilot.services.llm.nemotron_agent import NemotronAgent

class AgentFactory:
    """
    Factory pattern for Agent Orchestration.
    Allows seamless plug-and-play switching between Gemini, Nemotron, or custom agents
    without changing routing or business logic.
    """
    _registry: Dict[str, Type[BaseLLMAgent]] = {
        "gemini": GeminiAgent,
        "nemotron": NemotronAgent,
    }
    _instances: Dict[str, BaseLLMAgent] = {}

    @classmethod
    def register(cls, name: str, agent_cls: Type[BaseLLMAgent]) -> None:
        """Register a new LLM agent plugin."""
        cls._registry[name.lower()] = agent_cls

    @classmethod
    def get_agent(
        cls,
        provider: Optional[str] = None,
        graph_store: Optional[BaseGraphStore] = None
    ) -> BaseLLMAgent:
        """
        Retrieves or instantiates the requested LLM agent.
        Defaults to GEMINI (or environment variable LLM_PROVIDER).
        """
        chosen_provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()
        
        # If special graph_store is provided, instantiate fresh
        if graph_store:
            agent_cls = cls._registry.get(chosen_provider, GeminiAgent)
            return agent_cls(graph_store=graph_store)

        if chosen_provider not in cls._instances:
            agent_cls = cls._registry.get(chosen_provider, GeminiAgent)
            cls._instances[chosen_provider] = agent_cls()

        return cls._instances[chosen_provider]

# Global default agent instance
default_agent = AgentFactory.get_agent()

