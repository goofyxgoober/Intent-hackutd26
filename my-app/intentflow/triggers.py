"""Engine trigger facade (Section 5).

Exposes exactly two entry points: trigger_query and trigger_hypothesis_generation.
Chat router is their only caller (enforced by AST tests).
"""
from pathlib import Path
from typing import Any, List, Optional

from app.config import settings
from .agents.hypothesis_generator import HypothesisGenerator
from .agents.query_agent import CodebaseQueryEngine
from .models import GenerationResult, JevDecision, QueryResult, RouterResult


async def trigger_query(
    *,
    workspace: Any,
    user_id: str,
    message: str,
    history: Optional[List[Any]] = None,
    selected_tenet_id: Optional[str] = None,
    route: Optional[RouterResult] = None,
    provider: Optional[str] = None,
    llm: Optional[Any] = None,
    gemini_client: Optional[Any] = None,
) -> QueryResult:
    """Executes a read-only query over the codebase and intent structures.

    MUST NOT import or call any engine/store write method.
    """
    store = getattr(workspace, "store", workspace)
    repo_dir = getattr(workspace, "repo_dir", None)
    if repo_dir is None:
        wid = getattr(store, "wid", 0) or getattr(workspace, "id", 0)
        repo_dir = Path(settings.data_dir) / "workspaces" / str(wid) / "repo"

    engine = CodebaseQueryEngine(
        workspace=workspace,
        store=store,
        repo_dir=Path(repo_dir),
        llm=llm,
        gemini_client=gemini_client,
    )
    return await engine.execute_query(
        message=message,
        history=history,
        selected_tenet_id=selected_tenet_id,
        route=route,
        provider=provider,
    )


async def trigger_hypothesis_generation(
    *,
    workspace: Any,
    user_id: str,
    decision: JevDecision,
    llm: Optional[Any] = None,
) -> GenerationResult:
    """Executes hypothesis generation authorized by a JevDecision capability token.

    First statement asserts decision authorization (Rule 15).
    """
    # First statement: capability token verification
    decision.assert_authorizes_generation()

    store = getattr(workspace, "store", workspace)
    repo_dir = getattr(workspace, "repo_dir", None)
    if repo_dir is None:
        wid = getattr(store, "wid", 0) or getattr(workspace, "id", 0)
        repo_dir = Path(settings.data_dir) / "workspaces" / str(wid) / "repo"

    generator = HypothesisGenerator(
        workspace=workspace,
        store=store,
        repo_dir=Path(repo_dir),
        llm=llm,
    )
    return await generator.generate(decision, user_id=user_id)
