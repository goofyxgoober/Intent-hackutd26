from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
from app.copilot.models.schemas import (
    ChatMessage,
    IntentNode,
    IntentEdge,
    IntentGraph,
    SingleBotResponse,
    TestGenResponse,
    TokenMetrics,
)

# ---------------------------------------------------------------------------
# Abstract Base Interfaces (Contracts for Plug-and-Play Extensibility)
# ---------------------------------------------------------------------------

class BaseGraphStore(ABC):
    """Abstract interface for Graph Storage and Retrieval Engines."""

    @abstractmethod
    def get_graph(self) -> IntentGraph:
        """Returns the full graph representation."""
        pass

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[IntentNode]:
        """Fetches a single node by its unique identifier."""
        pass

    @abstractmethod
    def add_node(self, node: IntentNode) -> None:
        """Adds or updates an IntentNode in the graph."""
        pass

    @abstractmethod
    def add_edge(self, edge: IntentEdge) -> None:
        """Adds a directed dependency edge between two nodes."""
        pass

    @abstractmethod
    def retrieve_relevant_nodes(self, query: str, max_nodes: int = 3) -> List[IntentNode]:
        """Retrieves nodes matching semantic or structural queries."""
        pass

    @abstractmethod
    def get_raw_code_corpus(self, relevant_nodes: List[IntentNode]) -> str:
        """Generates raw syntax context for comparative RAG benchmarks."""
        pass

    @abstractmethod
    def reset_to_default(self) -> None:
        """Resets the graph to the baseline benchmark state."""
        pass


class BaseLLMAgent(ABC):
    """Abstract interface for Modernization & Test Orchestration Agents."""

    @abstractmethod
    async def execute_chat(
        self,
        user_message: str,
        history: Optional[List[ChatMessage]] = None,
        selected_node_ids: Optional[List[str]] = None,
    ) -> SingleBotResponse:
        """Executes interactive chat conditioned on the Intent Graph."""
        pass

    @abstractmethod
    async def generate_deterministic_test_suite(
        self,
        node_id: str,
        framework: str = "pytest"
    ) -> TestGenResponse:
        """Synthesizes unit tests enforcing the node's business invariants."""
        pass

    @abstractmethod
    async def extract_intent_from_code(
        self,
        code_snippet: str,
        file_path: str,
        language: str = "python"
    ) -> IntentNode:
        """Abstracts raw syntax/AST into an IntentNode JSON object."""
        pass

    @abstractmethod
    def trace_blast_radius(self, node_id: str) -> Dict[str, Any]:
        """Calculates downstream transitive dependency blast radius."""
        pass

    @abstractmethod
    def calculate_token_savings(self, node_ids: List[str]) -> Dict[str, Any]:
        """Quantifies token reduction between raw syntax and intent representations."""
        pass


class BaseTestRunner(ABC):
    """Abstract interface for test execution and invariant verification."""

    @abstractmethod
    async def run_invariant_tests(
        self,
        node_id: str,
        custom_test_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Executes invariant test suites and returns assertion verification metrics."""
        pass


class BaseTokenService(ABC):
    """Abstract interface for token estimation, pricing, and benchmark metrics."""

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        pass

    @abstractmethod
    def calculate_token_metrics(
        self, prompt_text: str, completion_text: str, latency_ms: float = 0.0
    ) -> TokenMetrics:
        pass

    @abstractmethod
    def compare_metrics(
        self, raw_metrics: TokenMetrics, intent_metrics: TokenMetrics
    ) -> Tuple[int, float, float, float]:
        pass

