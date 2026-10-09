"""The provider interface, typed errors, usage and cost."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from ..config import Config

ErrorKind = Literal[
    "billing", "rate_limit", "server", "timeout", "auth", "refusal", "invalid", "unavailable",
]


class ProviderError(RuntimeError):
    """`spent` is set when the failed call was still billed (refusal, truncation, bad JSON),
    so the ledger and the budget guard see every token paid for."""

    def __init__(self, kind: ErrorKind, message: str, spent: LLMResponse | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.spent = spent


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class LLMCall:
    stage: Literal["analyze", "tailor", "repair", "letter"]
    role: Literal["analyze", "tailor"]  # which configured model to use
    system: str  # static, cacheable
    user: str  # per-run
    schema: type[BaseModel]
    model_override: str | None = None


@dataclass
class LLMResponse:
    text: str
    usage: Usage
    provider: str
    model: str
    cost_usd: float


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(self, call: LLMCall) -> LLMResponse: ...


def cost_usd(config: Config, model: str, u: Usage) -> float:
    price = config.pricing.models.get(model)
    if price is None:
        return 0.0
    total = (u.input_tokens * price.input + u.output_tokens * price.output
             + u.cache_write_tokens * price.cache_write + u.cache_read_tokens * price.cache_read)
    return round(total / 1_000_000, 6)


_DROP = {"title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
         "minLength", "maxLength", "minItems", "maxItems", "pattern", "format"}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema every provider accepts: refs inlined, every property required,
    `additionalProperties: false`, numeric/length constraints removed (Pydantic still
    enforces them after parsing)."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {k: walk(v) for k, v in node.items() if k not in _DROP}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"])
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    result: dict[str, Any] = walk(raw)
    return result
