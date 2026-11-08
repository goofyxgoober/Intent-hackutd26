"""Data models, enums, exceptions, and content hashing for IntentFlow."""
import hashlib
import json
import secrets
import time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Status(str, Enum):
    HYPOTHESIS = "hypothesis"
    AXIOM = "axiom"
    SCRAPPED = "scrapped"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    STALE = "stale"
    NONE = "none"


class Actor(str, Enum):
    USER = "user"
    BUILDER = "builder"
    TEST_RUNNER = "test_runner"
    ENGINE = "engine"
    CHATBOT = "chatbot"


class PermissionDenied(Exception):
    """Raised when an actor attempts an action not permitted by the spec matrix."""
    pass


class EngineError(Exception):
    """Structured engine error matching CHATBOT_INTEGRATION.md error codes."""
    def __init__(self, code: str, message: str, data: Optional[Dict[str, Any]] = None, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        self.hint = hint

    def to_dict(self) -> Dict[str, Any]:
        out = {"code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.data:
            out["data"] = self.data
        return out


class StructuredFailure(Exception):
    """Raised when Nemotron output fails structured schema validation after retries."""
    pass


def new_id(prefix: str) -> str:
    """Generate a prefixed unique ID, e.g. t_9f3a1c2e, c_77aa01bd, p_1234abcd."""
    return f"{prefix}_{secrets.token_hex(6)}"


class CodeLink(BaseModel):
    file: str = Field(description="Repository-relative file path")
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)
    symbol: Optional[str] = None
    chunk_hash: Optional[str] = None
    confidence: str = "high"

    @model_validator(mode="before")
    @classmethod
    def normalize_path(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "path" in data and "file" not in data:
                data["file"] = data["path"]
        return data

    @property
    def path(self) -> str:
        return self.file


class Claim(BaseModel):
    id: str
    tenet_id: str
    status: Status = Status.HYPOTHESIS
    statement: str
    test_explanation: str = ""
    test_implementation: str = ""
    dependencies: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    unverified: bool = False
    accepted_without_verification: bool = False
    flagged: bool = False
    flag_reason: Optional[str] = None
    base_flag: Optional[str] = None  # "unlocked_base", "changed_base", etc.

    @model_validator(mode="before")
    @classmethod
    def handle_test_impl_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "test_impl" in data and "test_implementation" not in data:
                data["test_implementation"] = data["test_impl"]
        return data

    @property
    def test_impl(self) -> str:
        return self.test_implementation

    @test_impl.setter
    def test_impl(self, value: str) -> None:
        self.test_implementation = value

    def content_hash(self) -> str:
        """Hash of statement and test sections; results bind to this (Rule 6)."""
        body = json.dumps([self.statement, self.test_explanation, self.test_implementation])
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


class Tenet(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    level: int = 0
    functionality: str = ""
    children: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    cross_cutting: List[str] = Field(default_factory=list)
    code_links: List[CodeLink] = Field(default_factory=list)
    open_unknowns: List[str] = Field(default_factory=list)
    proposed_unreviewed: bool = False
    provenance: Dict[str, Any] = Field(default_factory=dict)


class TestRunRecord(BaseModel):
    __test__ = False
    timestamp: float = Field(default_factory=time.time)
    claim_hash: str
    verdict: Verdict
    invoked: str = ""
    expected: str = ""
    actual: str = ""
    flaky: bool = False
    code_ref: Optional[str] = None
    notes: str = ""
    underspecified: Optional[str] = None
    localized: Optional[str] = None  # "child_failure" | "composition"


class ResultFile(BaseModel):
    claim_id: str
    tenet_id: str
    runs: List[TestRunRecord] = Field(default_factory=list)


class PendingConfirmation(BaseModel):
    id: str
    claim_id: str
    target: Status
    claim_hash: str
    verified: Optional[bool] = None
    impact: Dict[str, Any] = Field(default_factory=dict)
    expires: float
    requires_reason: bool = False


# ==============================================================================
# Two-Mode Terminal (Query <-> Hypothesis Generation) Models
# ==============================================================================

class PromptVerdict(str, Enum):
    QUERY = "query"
    HYPOTHESIS_GENERATION = "hypothesis_generation"
    AXIOM_MODIFICATION_REQUEST = "axiom_modification_request"


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    start_line: int
    end_line: int


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: Literal["locate", "explain", "invariants", "dependencies", "impact", "overview", "other"] = "other"
    files: List[str] = Field(default_factory=list, max_length=8)
    tenets: List[str] = Field(default_factory=list, max_length=4)
    claims: List[str] = Field(default_factory=list, max_length=10)
    needs_source: bool = False
    source_requests: List[SourceRequest] = Field(default_factory=list, max_length=6)
    keywords: List[str] = Field(default_factory=list)
    rounds: int = 1
    fallback_used: bool = False


class RouterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: PromptVerdict
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=200)
    requested_count: Optional[int] = Field(default=None, ge=1, le=5)
    focus: Optional[str] = Field(default=None, max_length=200)
    plan: Optional[QueryPlan] = None
    degraded: bool = False

    @model_validator(mode="after")
    def sanitize_plan(self) -> "RouterResult":
        # Discard plan if present with any non-query verdict (§2.2)
        if self.verdict != PromptVerdict.QUERY:
            self.plan = None
        return self


class JevDecision(BaseModel):
    decision_id: str
    verdict: PromptVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["jev_llm", "explicit_user"] = "jev_llm"
    approved: bool = False
    gate_reason: Optional[str] = None
    target_tenet_id: Optional[str] = None
    degraded: bool = False
    requested_count: Optional[int] = None
    focus: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

    def assert_authorizes_generation(self) -> None:
        if not self.approved:
            raise PermissionDenied(f"Decision does not authorize generation: {self.gate_reason}")
        if self.verdict != PromptVerdict.HYPOTHESIS_GENERATION:
            raise PermissionDenied(f"Verdict is {self.verdict}, not hypothesis_generation")
        if not self.target_tenet_id:
            raise PermissionDenied("Target tenet ID missing from decision")


class CandidateReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    contradicts_axiom_ids: List[str] = Field(default_factory=list)
    testable: bool = True
    semantic_duplicate_of: Optional[str] = None
    issues: List[str] = Field(default_factory=list)


class CandidateReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: List[CandidateReviewItem] = Field(default_factory=list)


class QueryAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    insufficient_context: bool = False
    missing: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    suggested_followups: List[str] = Field(default_factory=list)


class Citation(BaseModel):
    kind: Literal["file", "tenet", "claim"]
    path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    id: Optional[str] = None
    valid: bool = True


class QueryResult(BaseModel):
    run_id: str
    question_type: str = "explain"
    plan: Dict[str, Any] = Field(default_factory=dict)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    insufficient_context: bool = False
    missing: List[str] = Field(default_factory=list)
    suggested_followups: List[str] = Field(default_factory=list)
    usage: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    error_code: Optional[str] = None
    answer: str = ""


class GenerationResult(BaseModel):
    run_id: str
    status: str = "completed"  # "completed" | "failed"
    tenet_id: str
    claims_created: List[Dict[str, Any]] = Field(default_factory=list)
    dropped_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = None
    summary: str = ""

