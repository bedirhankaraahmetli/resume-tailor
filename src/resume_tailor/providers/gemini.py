"""Gemini API free tier: fallback 2.

Free-tier content may be used by Google and read by human reviewers; redaction (which
runs before every provider) is what keeps contact details out of it.

The SDK does not honour the server's `retryDelay` on 429 (and does not retry at all
unless configured), so we read RetryInfo ourselves. A per-day quota is not worth waiting
for: it fails over immediately.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from ..config import Config
from .base import LLMCall, LLMResponse, ProviderError, Usage, strict_schema

MAX_WAIT_S = 90.0


def _retry_delay(details: Any) -> tuple[float | None, bool]:
    """(seconds to wait, is_daily_quota) from a google.rpc error body."""
    delay, daily = None, False
    items = (details or {}).get("error", {}).get("details", []) if isinstance(details, dict) else []
    for item in items:
        t = item.get("@type", "")
        if t.endswith("RetryInfo"):
            m = re.match(r"([\d.]+)s", str(item.get("retryDelay", "")))
            if m:
                delay = float(m.group(1))
        if t.endswith("QuotaFailure"):
            for v in item.get("violations", []):
                if "PerDay" in str(v.get("quotaId", "")):
                    daily = True
    return delay, daily


class GeminiProvider:
    name = "gemini"

    def __init__(self, config: Config, client: Any | None = None,
                 sleep: Any = time.sleep) -> None:
        self.config = config
        self.cfg = config.providers.gemini
        self._client = client
        self._sleep = sleep

    def available(self) -> bool:
        return self._client is not None or bool(os.environ.get("GEMINI_API_KEY"))

    def complete(self, call: LLMCall) -> LLMResponse:
        from google import genai
        from google.genai import errors, types

        client = self._client or genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        model = call.model_override or self.cfg.model
        config = types.GenerateContentConfig(
            system_instruction=call.system,
            response_mime_type="application/json",
            response_json_schema=strict_schema(call.schema),
            thinking_config=(types.ThinkingConfig(thinking_level=self.cfg.thinking_level)
                             if self.cfg.thinking_level else None),
        )
        for attempt in range(self.cfg.max_retries + 1):
            try:
                resp = client.models.generate_content(model=model, contents=call.user,
                                                      config=config)
                break
            except errors.ClientError as e:
                if e.code == 429:
                    delay, daily = _retry_delay(getattr(e, "details", None))
                    if daily or attempt == self.cfg.max_retries:
                        raise ProviderError("rate_limit", "Gemini free-tier quota exhausted") from e
                    self._sleep(min(delay or 2.0 * 2**attempt, MAX_WAIT_S))
                    continue
                if e.code in (401, 403):
                    raise ProviderError("auth", "Gemini API key rejected") from e
                raise ProviderError("invalid", f"Gemini rejected the request ({e.code})") from e
            except errors.ServerError as e:
                if attempt == self.cfg.max_retries:
                    raise ProviderError("server", f"Gemini server error ({e.code})") from e
                self._sleep(min(2.0 * 2**attempt, MAX_WAIT_S))
        else:  # pragma: no cover - loop always breaks or raises
            raise ProviderError("server", "Gemini retries exhausted")

        um = getattr(resp, "usage_metadata", None)
        usage = Usage(
            input_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
            # Thinking tokens are billed (and limited) as output.
            output_tokens=int(getattr(um, "candidates_token_count", 0) or 0)
            + int(getattr(um, "thoughts_token_count", 0) or 0),
            cache_read_tokens=int(getattr(um, "cached_content_token_count", 0) or 0),
        )
        text = resp.text or ""
        if not text:
            raise ProviderError("invalid", "Gemini returned no text",
                                LLMResponse("", usage, self.name, model, 0.0))
        return LLMResponse(text, usage, self.name, model, 0.0)
