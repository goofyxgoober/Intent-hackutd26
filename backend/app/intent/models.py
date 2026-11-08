"""Request bodies for the intent engine (spec sections 4, 5, 10.6, 12)."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ID = r"^[tc]_[A-Za-z0-9]{6,32}$"


class Provenance(BaseModel):
    run_id: Optional[str] = None
    commit_range: Optional[str] = None
    via: Optional[Literal["grilling", "test_generation", "jev", "remake", "manual", "sync", "chat"]] = None


class CodeLink(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)
    symbol: Optional[str] = Field(default=None, max_length=200)
    chunk_hash: Optional[str] = Field(default=None, max_length=128)


class TenetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    functionality: str = ""
    parent_id: Optional[str] = Field(default=None, pattern=ID)
    cross_cutting: List[str] = []
    provenance: Provenance = Provenance()


class TenetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    functionality: Optional[str] = None
    children: Optional[List[str]] = None  # reorder only; same set of ids
    cross_cutting: Optional[List[str]] = None


class ClaimFields(BaseModel):
    statement: Optional[str] = None
    test_explanation: Optional[str] = None
    test_implementation: Optional[str] = None
    dependencies: Optional[List[str]] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class ClaimCreate(BaseModel):
    statement: str = Field(min_length=1)
    test_explanation: str = ""
    test_implementation: str = ""
    dependencies: List[str] = []
    confidence: float = Field(default=0.5, ge=0, le=1)
    provenance: Provenance = Provenance()


class AxiomEdit(ClaimFields):
    acknowledge_warning: bool = False
    reason: str = ""


class Promote(BaseModel):
    accept_without_verification: bool = False


class Demote(BaseModel):
    reason: str = Field(min_length=1)


class Scrap(BaseModel):
    reason: str = Field(min_length=1)
    rejected_interpretation: Optional[str] = None


class Remake(ClaimCreate):
    pass


class TestRun(BaseModel):
    claim_hash: str = Field(min_length=64, max_length=64)
    verdict: Literal["pass", "fail", "inconclusive"]
    invoked: str = ""
    expected: str = ""
    actual: str = ""
    notes: str = ""
    # Commit of the legacy code under test. Runs only count as identical (for the
    # determinism check) when both the Claim wording and this commit match.
    code_ref: Optional[str] = Field(default=None, max_length=64)
    # Set when the recipe was ambiguous; the verdict must then be inconclusive.
    underspecified: Optional[str] = None


class Annotation(BaseModel):
    file_hash: Optional[str] = None
    summary: str = ""
    chunks: List[dict] = []


class JevVerdict(BaseModel):
    verdict: Literal["no_disruption", "update_existing", "new_branch", "axiom_conflict"]
    confidence: Literal["low", "medium", "high"]
    reason: str = Field(min_length=1, max_length=500)
    affected_tenets: List[str] = []
    affected_claims: List[str] = []
    batch_id: Optional[int] = None
    commit_range: Optional[str] = None


class SpecDoc(BaseModel):
    markdown: str
    sections: List[dict] = []
