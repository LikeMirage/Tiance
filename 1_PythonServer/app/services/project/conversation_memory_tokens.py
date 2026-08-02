from app.services.llm.usage.estimation import (
    estimate_json_token_count,
    estimate_request_context_tokens,
    estimate_token_count,
)

def compression_ratio_percent(source_tokens: int, compressed_tokens: int) -> float:
    if source_tokens <= 0:
        return 0.0
    return round((compressed_tokens / source_tokens) * 100, 1)
