from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenEstimationSettings:
    ascii_chars_per_token: float
    other_chars_per_token: float
    message_overhead_tokens: int
    image_placeholder_tokens: int
    updated_at: str | None = None


DEFAULT_TOKEN_ESTIMATION_SETTINGS = TokenEstimationSettings(
    ascii_chars_per_token=4.0,
    other_chars_per_token=2.0,
    message_overhead_tokens=4,
    image_placeholder_tokens=2000,
)
