"""Request files → staged runs → results (the GitHub Actions path)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from resume_tailor.build import find_pdflatex
from resume_tailor.jobs import (
    commit_message,
    finish,
    load_queue,
    pending_requests,
    run_queue_stage,
    start,
)
from resume_tailor.models import RunResult
from resume_tailor.providers.base import LLMCall, LLMResponse, Usage

needs_tex = pytest.mark.skipif(find_pdflatex() is None, reason="pdflatex not installed")


class Canned:
    """Answers each stage from the recorded sample fixtures, and counts calls."""

    name = "anthropic"

    def __init__(self, data: Path) -> None:
        self.analysis = (data / "fixtures/analysis.json").read_text("utf-8")
        self.tailoring = (data / "fixtures/tailoring.json").read_text("utf-8")
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def complete(self, call: LLMCall) -> LLMResponse:
        self.calls.append(call.stage)
        text = self.analysis if call.stage == "analyze" else self.tailoring
        return LLMResponse(text, Usage(1000, 500), "anthropic", "claude-sonnet-5-5", 0.01)


def _write(data: Path, name: str, body: object) -> Path:
    path = data / "requests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return path


def _app(data: Path, rid: str = "20261009-120000-northwind", **kw: object) -> Path:
    body = {"schema_version": 1, "type": "application", "id": rid,
            "posting": {"text": (data / "fixtures/posting.txt").read_text("utf-8")}, **kw}
    return _write(data, f"{rid}.json", body)


def _result(data: Path, rid: str) -> dict[str, object]:
    out: dict[str, object] = json.loads((data / "results" / f"{rid}.json").read_text("utf-8"))
    return out


def _all_stages(data: Path, work: Path, canned: Canned) -> list[bool]:
    return [run_queue_stage(data, work, s, providers={"anthropic": canned}, log=lambda _m: None)
            for s in ("analyze", "tailor", "compile")]


# ---------------------------------------------------------------- queueing


def test_pending_skips_requests_with_a_result(sample_dir: Path) -> None:
    _app(sample_dir, "a-1")
    _app(sample_dir, "a-2")
    (sample_dir / "results").mkdir(exist_ok=True)
    (sample_dir / "results/a-1.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in pending_requests(sample_dir)] == ["a-2.json"]


@pytest.mark.parametrize(("body", "error"), [
    ("{not json", "not valid JSON"),
    ({"schema_version": 1, "type": "application", "id": "x-1"}, "posting"),
    ({"schema_version": 1, "type": "cover", "id": "x-1"}, "unknown request type"),
    ({"schema_version": 1, "type": "application", "id": "x-1", "posting": {"text": "p"},
      "provider": "openai"}, "unknown provider"),
    ({"schema_version": 1, "type": "preset", "id": "x-1", "presets": ["nope"]},
     "unknown preset"),
    ({"schema_version": 1, "type": "application", "id": "../../evil",
      "posting": {"text": "p"}}, "request id must be"),
])
def test_bad_requests_fail_with_a_readable_result(sample_dir: Path, tmp_path: Path,
                                                  body: object, error: str) -> None:
    _write(sample_dir, "x-1.json", body)
    start(sample_dir, tmp_path / "work")
    [res] = finish(sample_dir, tmp_path / "work")
    assert res.status == "failed" and res.error and error in res.error
    # The result is named after the file when the id is unusable, so it stays inside results/
    assert (sample_dir / "results/x-1.json").exists()
    assert not list(sample_dir.glob("../evil*"))
    # ... and once it has a result, it is not pending any more (never silently retried)
    assert pending_requests(sample_dir) == []


def test_explicit_request_must_be_under_requests(sample_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        start(sample_dir, tmp_path / "work", [Path("config.yml")])


def test_stopped_workflow_still_writes_a_failed_result(sample_dir: Path, tmp_path: Path) -> None:
    _app(sample_dir)
    work = tmp_path / "work"
    start(sample_dir, work)
    canned = Canned(sample_dir)
    assert run_queue_stage(sample_dir, work, "analyze", providers={"anthropic": canned},
                           log=lambda _m: None)
    # ...and the runner is cancelled here, before "tailor".
    [res] = finish(sample_dir, work)
    assert res.status == "failed" and res.error and "during the tailor step" in res.error
    assert res.cost_usd == pytest.approx(0.01)  # the analyze call is still accounted for


def test_cover_letter_request_says_it_is_not_built_yet(sample_dir: Path, tmp_path: Path) -> None:
    _app(sample_dir, cover_letter=True)
    q = start(sample_dir, tmp_path / "work")
    assert any("Cover letters are not built yet" in n for n in q.jobs[0].notices)


def test_stale_preset_request_with_nothing_stale_is_done(sample_dir: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    import resume_tailor.jobs as jobs

    monkeypatch.setattr(jobs, "preset_status", lambda *_a: "up to date")
    _write(sample_dir, "p-1.json", {"schema_version": 1, "type": "preset", "id": "p-1",
                                    "presets": "stale"})
    start(sample_dir, tmp_path / "work")
    [res] = finish(sample_dir, tmp_path / "work")
    assert res.status == "done" and "nothing was built" in res.notices[0]
    assert commit_message([res]) == "tailor: presets (nothing to build)"


# ---------------------------------------------------------------- stages end to end


@needs_tex
def test_application_request_end_to_end(sample_dir: Path, tmp_path: Path) -> None:
    _app(sample_dir)
    work = tmp_path / "work"
    q = start(sample_dir, work)
    assert len(q.jobs) == 1
    canned = Canned(sample_dir)
    assert _all_stages(sample_dir, work, canned) == [True, True, True]
    assert canned.calls == ["analyze", "tailor"]
    assert load_queue(work).jobs[0].stage_done == "compile"
    [res] = finish(sample_dir, work)
    assert res.status == "done", res.error
    assert res.cost_usd == pytest.approx(0.02) and res.provider == "anthropic"
    folder = "Northwind Labs - Machine Learning Engineer (Junior)"
    assert res.folder == f"applications/{folder}"
    assert (sample_dir / res.files["en"]).exists() and (sample_dir / res.files["tr"]).exists()
    assert _result(sample_dir, "20261009-120000-northwind")["status"] == "done"
    rows = list(csv.DictReader((sample_dir / "applications.csv").open(encoding="utf-8")))
    assert rows[0]["request_id"] == "20261009-120000-northwind"
    usage = list(csv.DictReader((sample_dir / "usage.csv").open(encoding="utf-8")))
    assert [u["stage"] for u in usage] == ["analyze", "tailor"]
    assert commit_message([res]) == f"tailor: {folder}"
    assert pending_requests(sample_dir) == []


@needs_tex
def test_guard_failure_stops_later_stages_for_that_request_only(sample_dir: Path,
                                                                tmp_path: Path) -> None:
    _app(sample_dir, "a-1")
    _app(sample_dir, "a-2")
    work = tmp_path / "work"
    start(sample_dir, work)
    canned = Canned(sample_dir)
    good = canned.tailoring
    bad = good.replace("0.84", "0.97")
    answers = iter([bad, bad, good])  # a-1: tailor + repair both invent; a-2: fine

    def complete(call: LLMCall) -> LLMResponse:
        text = canned.analysis if call.stage == "analyze" else next(answers)
        return LLMResponse(text, Usage(10, 10), "anthropic", "claude-sonnet-5-5", 0.01)

    canned.complete = complete  # type: ignore[method-assign]
    assert _all_stages(sample_dir, work, canned) == [True, False, True]
    results = {r.id: r for r in finish(sample_dir, work)}
    assert results["a-1"].status == "failed" and "0.97" in (results["a-1"].error or "")
    assert results["a-2"].status == "done"
    assert commit_message(list(results.values())) == (
        "tailor: a-1 (failed); Northwind Labs - Machine Learning Engineer (Junior)")


@needs_tex
def test_preset_request_aggregates_one_result(sample_dir: Path, tmp_path: Path) -> None:
    _write(sample_dir, "p-1.json", {"schema_version": 1, "type": "preset", "id": "p-1",
                                    "presets": ["data-science-ml", "backend"]})
    work = tmp_path / "work"
    q = start(sample_dir, work)
    assert [j.run_id for j in q.jobs] == ["p-1--data-science-ml", "p-1--backend"]
    canned = Canned(sample_dir)
    assert all(_all_stages(sample_dir, work, canned))
    assert canned.calls == ["tailor", "tailor"]  # presets need no posting analysis
    [res] = finish(sample_dir, work)
    assert res.status == "done", res.error
    assert [r.id for r in res.runs] == ["data-science-ml", "backend"]
    assert res.cost_usd == pytest.approx(0.02)
    assert commit_message([res]) == "tailor: presets data-science-ml, backend"
    stored = RunResult.model_validate(_result(sample_dir, "p-1"))
    assert stored.runs[1].folder == "presets/Backend"


def test_commit_message_shapes() -> None:
    ok = RunResult(id="a", status="done", folder="applications/ABC Firm - Data Scientist")
    bad = RunResult(id="b-1", status="failed")
    assert commit_message([ok]) == "tailor: ABC Firm - Data Scientist"
    assert commit_message([ok, bad]) == "tailor: ABC Firm - Data Scientist; b-1 (failed)"
    assert commit_message([]) == "tailor: nothing to do"
