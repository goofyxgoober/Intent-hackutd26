"""Shared data contracts (CONTEXT.md section 5)."""
from typing import Dict, List

from pydantic import BaseModel, Field

NODE_ID_PATTERN = r"^[A-Za-z0-9_.:\-]{1,200}$"


class IntentNode(BaseModel):
    node_id: str = Field(pattern=NODE_ID_PATTERN)
    name: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    intent_summary: str = ""
    inputs: Dict[str, str] = {}
    outputs: Dict[str, str] = {}
    business_invariants: List[str] = []
    downstream_dependencies: List[str] = []


class IntentEdge(BaseModel):
    source: str = Field(pattern=NODE_ID_PATTERN)
    target: str = Field(pattern=NODE_ID_PATTERN)
    relation: str = Field(min_length=1, default="depends_on")


class IntentGraphIn(BaseModel):
    nodes: List[IntentNode]
    edges: List[IntentEdge] = []
