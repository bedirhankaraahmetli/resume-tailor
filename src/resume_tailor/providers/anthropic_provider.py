"""Claude API (prepaid credits): the default provider.

Structured JSON comes from structured outputs (`output_config.format`), not forced tool
use: Claude Sonnet 5.5 rejects `tool_choice: any/tool` with a 400. The static block
(rules, catalog, inventory, base resumes) is first and marked for prompt caching, so a
repair round or a preset batch within 5 minutes reads it at 0.1x.
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

import anthropic

from ..config import Config
from .base import LLMCall, LLMResponse, ProviderError, Usage, cost_usd, strict_schema

CREDITS_MESSAGE = (
    "Claude API credits are used up. Top up in the Claude Console, or keep using the fallback."
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, config: Config, client: Any | None = None) -> None:
        self.config = config
        self.cfg = config.providers.anthropic
        self._client = client

    def available(self) -> bool:
        return self._client is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))

    def model_for(self, call: LLMCall) -> str:
        if call.model_override:
            return call.model_override
        return self.cfg.tailor_model if call.role == "tailor" else self.cfg.analyze_model

    def complete(self, call: LLMCall) -> LLMResponse:
        client = self._client or anthropic.Anthropic(max_retries=2)
        model = self.model_for(call)
        effort = self.cfg.tailor_effort if call.role == "tailor" else self.cfg.analyze_effort
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": strict_schema(call.schema)},
        }
        if effort:
            output_config["effort"] = effort
        system_block: dict[str, Any] = {"type": "text", "text": call.system}
        if self.cfg.prompt_cache:
            system_block["cache_control"] = {"type": "ephemeral"}
        try:
            # Streaming avoids HTTP timeouts on long tailoring outputs.
            with client.messages.stream(
                model=model,
                max_tokens=self.cfg.max_tokens,
                system=cast(Any, [system_block]),
                messages=[{"role": "user", "content": call.user}],
                output_config=cast(Any, output_config),
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.APIStatusError as e:
            # A 402 has no dedicated SDK class; `type` carries the API's error type.
            if e.status_code == 402 or getattr(e, "type", None) == "billing_error":
                raise ProviderError("billing", CREDITS_MESSAGE) from e
            if isinstance(e, anthropic.RateLimitError):
                raise ProviderError("rate_limit", "Claude API rate limit") from e
            if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
                raise ProviderError("auth", "Claude API key rejected") from e
            if e.status_code >= 500:
                raise ProviderError("server", f"Claude API server error {e.status_code}") from e
            raise ProviderError("invalid", f"Claude API rejected the request ({e.status_code}): "
                                f"{getattr(e, 'message', '')}") from e
        except anthropic.APITimeoutError as e:
            raise ProviderError("timeout", "Claude API timed out") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("server", "cannot reach the Claude API") from e

        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        # Thinking blocks come first on Sonnet 5.5; the JSON is the text block.
        text = next((str(getattr(b, "text", "")) for b in msg.content if b.type == "text"), "")
        resp = LLMResponse(text, usage, self.name, model, cost_usd(self.config, model, usage))
        if msg.stop_reason == "refusal":
            raise ProviderError("refusal", "Claude declined the request", resp)
        if msg.stop_reason == "max_tokens":
            raise ProviderError("invalid", "output hit max_tokens; raise "
                                "providers.anthropic.max_tokens", resp)
        # Validate it is JSON here so the router can treat garbage as 'invalid'.
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError("invalid", f"response is not JSON: {e}", resp) from e
        return resp
