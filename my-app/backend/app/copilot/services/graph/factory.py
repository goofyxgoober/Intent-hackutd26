from typing import Dict, Type
from app.copilot.core.interfaces import BaseGraphStore
from app.copilot.services.graph.memory_graph import InMemoryGraphStore

class GraphStoreFactory:
    """
    Factory pattern for Graph Engines.
    Allows Indra and Vishjit to plug in alternative graph backends
    (e.g., SQLite, Neo4j, or Persistent JSON) without touching application logic.
    """
    _registry: Dict[str, Type[BaseGraphStore]] = {
        "memory": InMemoryGraphStore,
    }
    _instances: Dict[str, BaseGraphStore] = {}

    @classmethod
    def register(cls, name: str, store_cls: Type[BaseGraphStore]) -> None:
        """Register a new custom graph store plugin."""
        cls._registry[name] = store_cls

    @classmethod
    def get_store(cls, backend_type: str = "memory") -> BaseGraphStore:
        """Retrieves or instantiates a singleton instance of the chosen graph backend."""
        if backend_type not in cls._instances:
            if backend_type not in cls._registry:
                raise ValueError(f"Unknown graph backend '{backend_type}'. Registered: {list(cls._registry.keys())}")
            cls._instances[backend_type] = cls._registry[backend_type]()
        return cls._instances[backend_type]

# Default global instance
default_graph_store = GraphStoreFactory.get_store("memory")

