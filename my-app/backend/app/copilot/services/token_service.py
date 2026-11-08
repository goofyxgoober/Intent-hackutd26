import math
from typing import Tuple
from app.copilot.models.schemas import TokenMetrics

# NVIDIA Nemotron estimated pricing per 1M tokens ($0.70 / 1M prompt, $0.80 / 1M completion)
COST_PER_PROMPT_TOKEN = 0.70 / 1_000_000
COST_PER_COMPLETION_TOKEN = 0.80 / 1_000_000

def estimate_tokens(text: str) -> int:
    """
    Estimates token count with high accuracy across code and prose.
    Roughly 3.6 chars per token for code/structured JSON.
    """
    if not text:
        return 0
    # Code and whitespace-heavy text tends to average ~3.5-3.8 chars per token
    return max(1, math.ceil(len(text) / 3.65))

def calculate_token_metrics(prompt_text: str, completion_text: str, latency_ms: float = 0.0) -> TokenMetrics:
    prompt_tokens = estimate_tokens(prompt_text)
    completion_tokens = estimate_tokens(completion_text)
    total_tokens = prompt_tokens + completion_tokens
    
    cost = (prompt_tokens * COST_PER_PROMPT_TOKEN) + (completion_tokens * COST_PER_COMPLETION_TOKEN)
    
    return TokenMetrics(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(cost, 6),
        latency_ms=round(latency_ms, 2)
    )

def compare_metrics(raw_metrics: TokenMetrics, intent_metrics: TokenMetrics) -> Tuple[int, float, float, float]:
    """
    Returns (tokens_saved, percentage_saved, cost_saved_usd, latency_advantage_ms)
    """
    tokens_saved = max(0, raw_metrics.total_tokens - intent_metrics.total_tokens)
    percentage_saved = 0.0
    if raw_metrics.total_tokens > 0:
        percentage_saved = round((tokens_saved / raw_metrics.total_tokens) * 100, 2)
        
    cost_saved = round(max(0.0, raw_metrics.estimated_cost_usd - intent_metrics.estimated_cost_usd), 6)
    latency_adv = round(max(0.0, raw_metrics.latency_ms - intent_metrics.latency_ms), 2)
    
    return tokens_saved, percentage_saved, cost_saved, latency_adv

