"""
Backward-compatibility alias. Points to modular implementation in app.services.llm.factory.
"""
from app.copilot.services.llm.factory import default_agent as gemini_agent
from app.copilot.services.llm.gemini_agent import GeminiAgent
