"""Fallback, budget guard, repair round and cost accounting, with fake providers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from resume_tailor.config import load_config
from resume_tailor.ledger import Ledger
from resume_tailor.llm_input import repair_prompt
from resume_tailor.models import Analysis
from resume_tailor.providers.anthropic_provider import CREDITS_MESSAGE, AnthropicProvider
from resume_tailor.providers.base import LLMCall, LLMResponse, ProviderError, Usage, strict_schema
from resume_tailor.providers.gemini import _retry_delay
from resume_tailor.router import NoProviderError, Router

from conftest import SAMPLE

GOOD = (SAMPLE / "fixtures/analysis.json").read_text(encoding="utf-8")
CALL = LLMCall("analyze", "analyze", "system", "user", Analysis)


class Fake:
    def __init__(self, name: str, outputs: list[Any], available: bool = True,
                 cost: float = 0.01) -> None:
        self.name, self.outputs, self._available, self.cost = name, list(outputs), available, cost
        self.calls: list[LLMCall] = []

    def available(self) -> bool:
        return self._available

    def complete(self, call: LLMCall) -> LLMResponse:
        self.calls.append(call)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return LLMResponse(out, Usage(100, 50), self.name, f"{self.name}-model", self.cost)


def router(tmp_path: Path, *providers: Fake, budget: float = 5.0) -> Router:
    cfg = load_config(SAMPLE)
    cfg.monthly_budget_usd = budget
    cfg.providers.order = [p.name for p in providers]
    return Router(cfg, {p.name: p for p in providers}, Ledger(tmp_path, "run1", "application"),
                  repair_prompt)


def parse(text: str) -> Analysis:
    return Analysis.model_validate_json(text)


def test_first_provider_wins(tmp_path: Path) -> None:
    a = Fake("anthropic", [GOOD])
    value, _, prov = router(tmp_path, a, Fake("gemini", [])).run(CALL, parse)
    assert prov is a and value.company == "Northwind Labs"


def test_billing_error_falls_back_without_retry(tmp_path: Path) -> None:
    a = Fake("anthropic", [ProviderError("billing", CREDITS_MESSAGE)])
    g = Fake("gemini", [GOOD])
    r = router(tmp_path, a, g)
    _, _, prov = r.run(CALL, parse)
    assert prov is g and len(a.calls) == 1
    assert any("credits are used up" in n for n in r.notices)


def test_invalid_json_gets_one_repair_on_same_provider(tmp_path: Path) -> None:
    a = Fake("anthropic", ['{"company": 1}', GOOD])
    r = router(tmp_path, a)
    _, _, prov = r.run(CALL, parse)
    assert prov is a and len(a.calls) == 2
    assert a.calls[1].stage == "repair" and "Problems" in a.calls[1].user


def test_still_invalid_after_repair_falls_back(tmp_path: Path) -> None:
    a = Fake("anthropic", ["{}", "{}"])
    g = Fake("gemini", [GOOD])
    _, _, prov = router(tmp_path, a, g).run(CALL, parse)
    assert prov is g


def test_unavailable_provider_is_skipped(tmp_path: Path) -> None:
    a = Fake("anthropic", [], available=False)
    g = Fake("gemini", [GOOD])
    _, _, prov = router(tmp_path, a, g).run(CALL, parse)
    assert prov is g and not a.calls


def test_no_provider(tmp_path: Path) -> None:
    with pytest.raises(NoProviderError, match="none has credentials"):
        router(tmp_path, Fake("anthropic", [], available=False)).run(CALL, parse)


def test_budget_guard_skips_anthropic(tmp_path: Path) -> None:
    led = Ledger(tmp_path, "old", "application")
    led.record("tailor", LLMResponse("", Usage(), "anthropic", "m", 4.90))
    a, g = Fake("anthropic", [GOOD]), Fake("gemini", [GOOD])
    r = router(tmp_path, a, g, budget=5.0)  # 4.90 + 0.25 estimated > 5.00
    _, _, prov = r.run(CALL, parse)
    assert prov is g and not a.calls
    assert any("Budget guard" in n for n in r.notices)


def test_every_call_is_ledgered_including_failures(tmp_path: Path) -> None:
    spent = LLMResponse("not json", Usage(10, 10), "anthropic", "m", 0.02)
    a = Fake("anthropic", [ProviderError("invalid", "bad", spent), GOOD])
    r = router(tmp_path, a)
    r.run(CALL, parse)
    rows = list(csv.DictReader((tmp_path / "usage.csv").open(encoding="utf-8")))
    assert [row["stage"] for row in rows] == ["analyze", "repair"]
    assert r.total_cost == pytest.approx(0.03)


def test_month_spend_only_counts_this_month(tmp_path: Path) -> None:
    (tmp_path / "usage.csv").write_text(
        "timestamp,run_id,kind,stage,provider,model,input_tokens,output_tokens,"
        "cache_write_tokens,cache_read_tokens,cost_usd\n"
        "2020-01-05T00:00:00+00:00,x,application,tailor,anthropic,m,0,0,0,0,9.0\n",
        encoding="utf-8")
    assert Ledger(tmp_path, "r", "application").month_spend() == 0.0


# ---- providers --------------------------------------------------------------------------


def test_strict_schema_is_closed_and_ref_free() -> None:
    from resume_tailor.models import Tailoring

    s = strict_schema(Tailoring)

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            assert "$ref" not in n and "minimum" not in n
            if n.get("type") == "object" and "properties" in n:
                assert n["additionalProperties"] is False
                assert set(n["required"]) == set(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(s)


class _Err402(Exception):
    pass


def test_anthropic_billing_error_is_typed() -> None:
    import anthropic
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(402, request=req, json={
        "type": "error", "error": {"type": "billing_error", "message": "credit balance too low"}})
    err = anthropic.APIStatusError("credit balance too low", response=resp, body=None)

    class Client:
        class messages:
            @staticmethod
            def stream(**_: Any) -> Any:
                raise err

    p = AnthropicProvider(load_config(SAMPLE), client=Client())
    with pytest.raises(ProviderError) as e:
        p.complete(CALL)
    assert e.value.kind == "billing" and "Top up" in str(e.value)


def test_gemini_retry_delay_parsing() -> None:
    body = {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27s"},
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerMinutePerProject"}]},
    ]}}
    assert _retry_delay(body) == (27.0, False)
    body["error"]["details"][1]["violations"][0]["quotaId"] = "GenerateRequestsPerDayPerProject"
    assert _retry_delay(body) == (27.0, True)
