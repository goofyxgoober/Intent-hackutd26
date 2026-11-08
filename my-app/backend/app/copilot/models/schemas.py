from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Core Intent Graph Schemas (Contracts with Indra & Vishjit)
# ---------------------------------------------------------------------------

class IntentNode(BaseModel):
    """
    Every functional flow block extracted by Indra and Aadi's agents
    conforms to this contract.
    """
    node_id: str = Field(..., description="Unique identifier for the intent node, e.g., auth_flow_validate_session")
    name: str = Field(..., description="Human-readable functional name, e.g., Validate Session Token")
    source_file: str = Field(..., description="Path to the source file, e.g., src/auth/session.py")
    intent_summary: str = Field(..., description="High-level architectural intent description")
    inputs: Dict[str, str] = Field(default_factory=dict, description="Dictionary of input parameters and abstract types")
    outputs: Dict[str, str] = Field(default_factory=dict, description="Dictionary of outputs or exceptions produced")
    business_invariants: List[str] = Field(default_factory=list, description="Must-hold business rules and safety assertions")
    downstream_dependencies: List[str] = Field(default_factory=list, description="List of node_ids triggered or called")
    raw_code_snippet: Optional[str] = Field(default=None, description="Optional raw code snippet for comparative analysis")


class IntentEdge(BaseModel):
    source: str = Field(..., description="Origin node_id")
    target: str = Field(..., description="Destination node_id")
    relation: str = Field(default="triggers", description="Semantic relationship, e.g., triggers_on_valid_token")


class IntentGraph(BaseModel):
    repo_name: str = Field(..., description="Target repository name")
    nodes: List[IntentNode] = Field(default_factory=list, description="List of full IntentNode objects or IDs")
    edges: List[IntentEdge] = Field(default_factory=list, description="Directed dependencies between nodes")


# ---------------------------------------------------------------------------
# Chat & Nemotron Agent Schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message text content")
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(..., description="User query / modernization command")
    history: List[ChatMessage] = Field(default_factory=list)
    selected_node_ids: Optional[List[str]] = Field(default=None, description="Optional pinned or highlighted nodes")
    model: Optional[str] = Field(default="nvidia/llama-3.1-nemotron-70b-instruct")

class SessionChatRequest(BaseModel):
    message: str = Field(..., description="User query / modernization command")
    session_id: Optional[str] = Field(default=None, description="Omit to start a new chat session")
    selected_node_ids: Optional[List[str]] = Field(default=None, description="Optional pinned or highlighted nodes")

class TokenMetrics(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0


class SingleBotResponse(BaseModel):
    bot_type: str = Field(..., description="'raw_code_rag' or 'intent_graph_rag'")
    content: str
    token_metrics: TokenMetrics
    retrieved_items: List[str] = Field(default_factory=list, description="Names/files of retrieved context items")
    agent_steps: List[str] = Field(default_factory=list, description="Multi-step agentic execution trace / tool call chain")

class ChatResponse(SingleBotResponse):
    """SingleBotResponse plus the session this exchange was saved under."""
    session_id: str

class DualChatComparisonResponse(BaseModel):
    query: str
    raw_bot: SingleBotResponse
    intent_bot: SingleBotResponse
    tokens_saved: int
    percentage_saved: float
    cost_saved_usd: float
    latency_advantage_ms: float
    recommended_action: Optional[str] = None


# ---------------------------------------------------------------------------
# Test Generation & Intent Extraction Schemas
# ---------------------------------------------------------------------------

class ExtractionRequest(BaseModel):
    code_snippet: str = Field(..., description="Raw syntax block extracted from AST")
    file_path: str = Field(..., description="Source file relative path")
    language: str = Field(default="python", description="Language: python, typescript, java, etc.")


class TestGenRequest(BaseModel):
    node_id: str = Field(..., description="Target IntentNode ID to generate tests for")
    framework: str = Field(default="pytest", description="Testing framework: pytest, jest, unittest")
    target_coverage: Optional[str] = Field(default="invariants", description="'invariants' or 'full'")


class TestGenResponse(BaseModel):
    node_id: str
    node_name: str
    test_code: str
    invariants_covered: List[str]
    mock_setup: str
    explanation: str


class TestRunRequest(BaseModel):
    node_id: str = Field(..., description="Target IntentNode ID to run invariant tests for")
    custom_test_code: Optional[str] = Field(default=None, description="Optional custom test code to execute")


class TestRunItem(BaseModel):
    test_name: str
    status: str
    target_invariant: str


class TestRunResponse(BaseModel):
    node_id: str
    node_name: str
    overall_status: str
    total_invariants_tested: int
    total_tests_run: int
    passed: int
    failed: int
    pass_rate: str
    execution_time_ms: float
    test_results: List[TestRunItem]
    raw_output: str


class IntentExtractionResponse(BaseModel):
    node: IntentNode
    message: str
    tokens_saved_vs_raw: int
    percentage_saved: float

# ---------------------------------------------------------------------------
# Chat Session Schemas (persistence)
# ---------------------------------------------------------------------------

class SessionCreateRequest(BaseModel):
    title: Optional[str] = None
    selected_node_ids: List[str] = Field(default_factory=list)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    selected_node_ids: List[str]
    created_at: datetime
    last_active_at: datetime
    message_count: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    role: str
    content: str
    timestamp: datetime
    token_metrics: Optional[TokenMetrics] = None
    retrieved_items: Optional[List[str]] = None
    agent_steps: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Frontend Visualizer Contract Schemas (Vishjit / httpSource.ts bridge)
# ---------------------------------------------------------------------------

class FrontendAskRequest(BaseModel):
    question: str
    context: Optional[str] = None


class FrontendAskResponse(BaseModel):
    answer: str


class FrontendGeneratedTestItem(BaseModel):
    name: str
    code: Optional[str] = None
    invariant: Optional[str] = None


class FrontendGeneratedTests(BaseModel):
    node_id: str
    tests: List[FrontendGeneratedTestItem]
