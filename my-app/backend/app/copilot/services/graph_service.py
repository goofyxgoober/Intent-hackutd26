"""
Backward-compatibility alias. Points to modular implementation in app.services.graph.factory.
"""
from app.copilot.services.graph.factory import default_graph_store as graph_service
from app.copilot.services.graph.memory_graph import InMemoryGraphStore as GraphService
