"""CSV logs in the data repo.

`usage.csv` has one row per LLM call (including failed runs and preset builds, which
still cost money) and is what the budget guard sums. `applications.csv` has one row per
application; its `cost_usd` is that run's total.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .providers.base import LLMResponse

USAGE_FIELDS = ["timestamp", "run_id", "kind", "stage", "provider", "model", "input_tokens",
                "output_tokens", "cache_write_tokens", "cache_read_tokens", "cost_usd"]
APP_FIELDS = ["date", "company", "position", "folder", "provider", "model", "cost_usd",
              "match_pct", "status", "source", "request_id"]


def _append(path: Path, fields: list[str], row: dict[str, object]) -> None:
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass
class Ledger:
    data_dir: Path
    run_id: str
    kind: str  # application | preset

    @property
    def usage_path(self) -> Path:
        return self.data_dir / "usage.csv"

    def record(self, stage: str, r: LLMResponse) -> None:
        _append(self.usage_path, USAGE_FIELDS, {
            "timestamp": now_utc().isoformat(timespec="seconds"),
            "run_id": self.run_id, "kind": self.kind, "stage": stage,
            "provider": r.provider, "model": r.model,
            "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
            "cache_write_tokens": r.usage.cache_write_tokens,
            "cache_read_tokens": r.usage.cache_read_tokens,
            "cost_usd": f"{r.cost_usd:.6f}",
        })

    def month_spend(self, when: datetime | None = None) -> float:
        when = when or now_utc()
        prefix = when.strftime("%Y-%m")
        if not self.usage_path.exists():
            return 0.0
        total = 0.0
        with self.usage_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("timestamp", "").startswith(prefix):
                    try:
                        total += float(row.get("cost_usd") or 0)
                    except ValueError:
                        continue
        return round(total, 6)


def append_application(data_dir: Path, row: dict[str, object]) -> None:
    _append(data_dir / "applications.csv", APP_FIELDS, row)
