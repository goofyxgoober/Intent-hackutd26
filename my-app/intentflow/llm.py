"""Nemotron client with tiers, thinking flags, structured output, and retries."""
import json
import os
import re
from typing import Any, Dict, List, Optional, Type, TypeVar
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .models import StructuredFailure

T = TypeVar("T", bound=BaseModel)

MODELS = {
    "deep": os.getenv("NEMOTRON_DEEP", "nvidia/nemotron-3-ultra-550b-a55b"),
    "mid":  os.getenv("NEMOTRON_MID",  "nvidia/nemotron-3-super-120b-a12b"),
    "fast": os.getenv("NEMOTRON_FAST", "nvidia/nemotron-3-nano-30b-a3b"),
}

# Token tracking registry for Section 13 Token Counter
USAGE_LOGS: List[Dict[str, Any]] = []


def log_usage(agent: str, tier: str, prompt_tokens: int, completion_tokens: int, tier_of_context: str = "graph") -> None:
    USAGE_LOGS.append({
        "agent": agent,
        "tier": tier,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tier_of_context": tier_of_context,
    })


def get_token_stats() -> Dict[str, Any]:
    total_prompt = sum(u["prompt_tokens"] for u in USAGE_LOGS)
    total_completion = sum(u["completion_tokens"] for u in USAGE_LOGS)
    graph_count = sum(1 for u in USAGE_LOGS if u["tier_of_context"] == "graph")
    file_count = sum(1 for u in USAGE_LOGS if u["tier_of_context"] == "file")
    return {
        "total_calls": len(USAGE_LOGS),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "graph_tier_queries": graph_count,
        "file_tier_queries": file_count,
    }


class Nemotron:
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        if client is not None:
            self.client = client
        else:
            api_key = os.getenv("JEV_API_KEY") or os.getenv("NVIDIA_API_KEY", "dummy_key")
            base_url = os.getenv("NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1")
            self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=300)

    async def structured(
        self,
        tier: str,
        system: str,
        user: str,
        schema: Type[T],
        *,
        agent: str = "nemotron",
        context_tier: str = "graph",
        thinking: bool = True,
        medium_effort: bool = False,
        max_tokens: int = 8000,
        retries: int = 1,
    ) -> T:
        tool = {
            "type": "function",
            "function": {
                "name": "emit",
                "description": "Return the final result.",
                "parameters": schema.model_json_schema(),
            },
        }
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kwargs: Dict[str, Any] = {"enable_thinking": thinking, "force_nonempty_content": True}
        if thinking and medium_effort:
            kwargs["medium_effort"] = True

        last_err = ""
        for attempt in range(retries + 1):
            resp = await self.client.chat.completions.create(
                model=MODELS.get(tier, tier),
                messages=msgs,
                tools=[tool],
                tool_choice="required",
                max_tokens=max_tokens,
                temperature=1.0 if thinking else 0.2,
                top_p=0.95,
                extra_body={"chat_template_kwargs": kwargs},
            )
            usage = resp.usage
            if usage:
                log_usage(agent, tier, usage.prompt_tokens or 0, usage.completion_tokens or 0, context_tier)

            msg = resp.choices[0].message
            raw = None
            if msg.tool_calls:
                raw = msg.tool_calls[0].function.arguments
            elif msg.content:
                raw = re.sub(r"<think>.*?</think>", "", msg.content, flags=re.S).strip()
                m = re.search(r"\{.*\}", raw, flags=re.S)
                raw = m.group(0) if m else raw

            try:
                if not raw:
                    raise ValueError("Empty response payload from LLM")
                return schema.model_validate_json(raw)
            except (ValidationError, TypeError, ValueError) as e:
                last_err = str(e)[:1500]
                msgs.append({
                    "role": "user",
                    "content": f"Your last output failed schema validation:\n{last_err}\nCall emit again with a corrected payload.",
                })

        raise StructuredFailure(last_err)


class FakeLLM:
    """Mock LLM for fast unit testing and offline development."""

    def __init__(self, responses: Optional[List[Any]] = None):
        self.responses = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def set_responses(self, responses: List[Any]) -> None:
        self.responses = list(responses)

    async def structured(
        self,
        tier: str,
        system: str,
        user: str,
        schema: Type[T],
        *,
        agent: str = "fake",
        context_tier: str = "graph",
        thinking: bool = True,
        medium_effort: bool = False,
        max_tokens: int = 8000,
        retries: int = 1,
    ) -> T:
        self.calls.append({
            "tier": tier,
            "system": system,
            "user": user,
            "schema": schema,
            "agent": agent,
            "context_tier": context_tier,
        })
        log_usage(agent, tier, 10, 10, context_tier)

        last_err = ""
        for attempt in range(retries + 1):
            if not self.responses:
                raise StructuredFailure("FakeLLM ran out of canned responses: " + last_err)
            resp = self.responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            try:
                if isinstance(resp, str):
                    return schema.model_validate_json(resp)
                if isinstance(resp, dict):
                    return schema.model_validate(resp)
                return resp
            except (ValidationError, TypeError, ValueError) as e:
                last_err = str(e)
                continue

        raise StructuredFailure(f"Validation failed after {retries} retries: {last_err}")
