"""Provider selection, fallback, budget guard and the JSON repair round.

Fallback happens on: 5xx / rate limit / timeout after retries, billing errors, the budget
guard, missing credentials, refusals, and output that is still invalid after one repair
round. A fact-guard violation is *not* a reason to fall back (the pipeline repairs it on
the same provider and then fails): a different model inventing different facts is not a
fix.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import ValidationError

from .config import Config
from .ledger import Ledger
from .providers.base import LLMCall, LLMResponse, Provider, ProviderError

T = TypeVar("T")
RepairPrompt = Callable[[str, str, list[str]], str]  # (original user, bad output, errors)


class NoProviderError(RuntimeError):
    pass


@dataclass
class Router:
    config: Config
    providers: dict[str, Provider]
    ledger: Ledger
    repair_prompt: RepairPrompt
    first: str | None = None
    notices: list[str] = field(default_factory=list)
    responses: list[LLMResponse] = field(default_factory=list)
    _budget_checked: bool | None = None

    @property
    def order(self) -> list[str]:
        order = list(self.config.providers.order)
        if self.first:
            order = [self.first, *[p for p in order if p != self.first]]
        return order

    @property
    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.responses), 6)

    def _note(self, msg: str) -> None:
        if msg not in self.notices:
            self.notices.append(msg)

    def _record(self, stage: str, r: LLMResponse) -> None:
        self.responses.append(r)
        self.ledger.record(stage, r)

    def budget_blocks_anthropic(self) -> bool:
        if self._budget_checked is None:
            spent = self.ledger.month_spend()
            budget = self.config.monthly_budget_usd
            nxt = self.config.estimated_run_cost_usd
            self._budget_checked = spent + nxt > budget
            if self._budget_checked:
                self._note(f"Budget guard: this month's Claude API spend is ${spent:.2f} of "
                           f"${budget:.2f}; the next run (~${nxt:.2f}) would exceed it, so the "
                           "fallback provider was used.")
        return self._budget_checked

    def call_on(self, provider: Provider, call: LLMCall, parse: Callable[[str], T]
                ) -> tuple[T, LLMResponse]:
        """One call plus at most one JSON repair round, on a single provider."""
        try:
            resp = provider.complete(call)
        except ProviderError as e:
            if e.spent is not None:
                self._record(call.stage, e.spent)
            if e.kind != "invalid" or e.spent is None:
                raise
            resp = e.spent
            error_text = [str(e)]
        else:
            self._record(call.stage, resp)
            try:
                return parse(resp.text), resp
            except (ValidationError, ValueError) as e:
                error_text = _errors(e)
        repair = LLMCall("repair", call.role, call.system,
                         self.repair_prompt(call.user, resp.text, error_text), call.schema,
                         call.model_override)
        try:
            resp2 = provider.complete(repair)
        except ProviderError as e:
            if e.spent is not None:
                self._record("repair", e.spent)
            raise
        self._record("repair", resp2)
        try:
            return parse(resp2.text), resp2
        except (ValidationError, ValueError) as e:
            raise ProviderError("invalid", "output still invalid after one repair round: "
                                + "; ".join(_errors(e))[:500]) from e

    def run(self, call: LLMCall, parse: Callable[[str], T]
            ) -> tuple[T, LLMResponse, Provider]:
        tried: list[str] = []
        for name in self.order:
            provider = self.providers.get(name)
            if provider is None:
                continue
            if not provider.available():
                continue
            if name == "anthropic" and self.budget_blocks_anthropic():
                continue
            tried.append(name)
            try:
                value, resp = self.call_on(provider, call, parse)
                return value, resp, provider
            except ProviderError as e:
                self._note(f"{name}: {e}")
                continue
        raise NoProviderError(
            "no provider could complete the request"
            + (f" (tried: {', '.join(tried)})" if tried else
               " (none has credentials: set ANTHROPIC_API_KEY, log in to Claude Code, or set "
               "GEMINI_API_KEY)")
        )


def _errors(e: Exception) -> list[str]:
    if isinstance(e, ValidationError):
        return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()][:30]
    return [str(e)]
