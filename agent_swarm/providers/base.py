from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Optional, Protocol

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,}\"']+"),
    re.compile(
        r"(?i)([\"']?(?:api[_-]?key|token|secret|password|authorization)[\"']?"
        r"\s*[:=]\s*)([\"'])[^\"']*\2"
    ),
    re.compile(
        r"(?i)([\"']?(?:api[_-]?key|token|secret|password|authorization)[\"']?"
        r"\s*[:=]\s*)[^\s,}\"']+"
    ),
)


def redact_diagnostic(value: str, *, limit: int = 1000) -> str:
    """Redact common secret shapes and bound a diagnostic before persistence."""

    sensitive_keys = {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
    }

    def redact_json(item):
        if isinstance(item, dict):
            return {
                key: "<redacted>"
                if str(key).lower().replace("-", "_") in sensitive_keys
                else redact_json(nested)
                for key, nested in item.items()
            }
        if isinstance(item, list):
            return [redact_json(nested) for nested in item]
        return item

    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        redacted = value
    else:
        redacted = json.dumps(redact_json(parsed), sort_keys=True)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(r"\1<redacted>", redacted)
    if len(redacted) <= limit:
        return redacted
    marker = "...<truncated>..."
    remaining = max(0, limit - len(marker))
    head = remaining // 2
    tail = remaining - head
    return redacted[:head] + marker + redacted[-tail:]


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        usage: Optional["TokenUsage"] = None,
        duration_seconds: Optional[float] = None,
    ):
        super().__init__(message)
        self.transient = transient
        self.usage = usage
        self.duration_seconds = duration_seconds


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_output_tokens: Optional[int] = None
    cache_write_input_tokens: Optional[int] = None
    provider_reported_cost_usd: Optional[float] = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        for field_name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "cache_write_input_tokens",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer")
        cost = self.provider_reported_cost_usd
        if cost is not None and (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or cost < 0
        ):
            raise ValueError(
                "provider_reported_cost_usd must be finite and non-negative"
            )

    @property
    def total_tokens(self) -> Optional[int]:
        values = (self.input_tokens, self.output_tokens)
        if any(value is None for value in values):
            return None
        return sum(value or 0 for value in values)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ProviderResult:
    output: str
    usage: TokenUsage
    provider: str
    model: str
    duration_seconds: float
    raw_event_count: int = 0
    session_id: Optional[str] = None


class ModelProvider(Protocol):
    name: str

    async def run(
        self,
        prompt: str,
        *,
        model: str,
        title: str,
        cwd: str,
    ) -> ProviderResult: ...
