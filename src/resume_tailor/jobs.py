"""Request files → staged pipeline runs, for GitHub Actions (PROMPT.md §8, PLAN.md §2.9).

The workflow runs `start`, then one step per stage (`analyze`, `tailor`, `compile`), then
`finish`. The Actions API exposes step status, so the web app can show which stage is
running. State between steps goes through a checkpoint file (`<work>/queue.json`) outside
the data repo, so it is never committed.

**Every pending request is processed, not only the one that triggered the run.** GitHub
keeps at most one pending run per concurrency group and cancels the others, so a request
whose own run was cancelled would otherwise never be built. A request is pending while
`results/<id>.json` does not exist; `finish` writes that file for every request it took,
success or failure, so nothing is built twice and a failure is never silently retried
(each retry would spend credits again).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .config import load_config, load_presets
from .ledger import Ledger
from .llm_input import repair_prompt
from .models import Analysis, ApplicationRequest, PresetRequest, RunResult, Tailoring
from .pipeline import (
    STAGES,
    RunRequest,
    RunState,
    Stage,
    default_providers,
    describe,
    finish_result,
    run_stage,
    write_result,
)
from .presets import status as preset_status
from .providers.base import LLMResponse, Provider, Usage
from .router import Router

PROVIDERS = ("anthropic", "claude-code", "gemini")
# The id names results/<id>.json, so it must not be able to leave that folder.
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class Job(BaseModel):
    """One pipeline run. An application request is one job; a preset request is one job
    per preset, all reported in a single result file."""

    request_id: str
    run_id: str
    request_path: str
    kind: str = "application"
    preset_id: str | None = None
    posting: str | None = None
    company: str | None = None
    position: str | None = None
    provider: str | None = None
    model: str | None = None
    note: str | None = None
    stage_done: str | None = None
    failed: bool = False
    result: RunResult
    # RunState and router state, carried between steps
    analysis: Analysis | None = None
    tailoring: Tailoring | None = None
    raw_tailoring: str | None = None
    repaired: list[str] = Field(default_factory=list)
    responses: list[dict[str, object]] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class Queue(BaseModel):
    jobs: list[Job] = Field(default_factory=list)


def _queue_path(work: Path) -> Path:
    return work / "queue.json"


def load_queue(work: Path) -> Queue:
    path = _queue_path(work)
    if not path.exists():
        return Queue()
    return Queue.model_validate_json(path.read_text(encoding="utf-8"))


def save_queue(work: Path, q: Queue) -> None:
    work.mkdir(parents=True, exist_ok=True)
    _queue_path(work).write_text(q.model_dump_json(indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------------------
# start


def pending_requests(data_dir: Path) -> list[Path]:
    reqs = sorted((data_dir / "requests").glob("**/*.json"))
    return [p for p in reqs if not (data_dir / "results" / f"{_id_for(p)}.json").exists()]


def _id_for(path: Path) -> str:
    """The id from the file's content when it is valid, else the file name."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rid = raw.get("id") if isinstance(raw, dict) else None
    except (OSError, ValueError):
        rid = None
    if isinstance(rid, str) and ID_RE.match(rid):
        return rid
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", path.stem)[:100].lstrip("._-")
    return stem or "request"


def _failed(rid: str, path: str, kind: Literal["application", "preset"],
            error: str) -> Job:
    return Job(request_id=rid, run_id=rid, request_path=path, kind=kind, failed=True,
               result=RunResult(id=rid, status="failed", kind=kind,
                                error=error))


def jobs_for(data_dir: Path, path: Path) -> list[Job]:
    rel = path.relative_to(data_dir).as_posix()
    rid = _id_for(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [_failed(rid, rel, "application", f"request file is not valid JSON: {e}")]
    rtype = raw.get("type", "application") if isinstance(raw, dict) else "application"
    if rtype not in ("application", "preset"):
        return [_failed(rid, rel, "application", f"unknown request type {rtype!r}")]
    kind: Literal["application", "preset"] = "preset" if rtype == "preset" else "application"
    try:
        if kind == "preset":
            preq = PresetRequest.model_validate(raw)
        else:
            areq = ApplicationRequest.model_validate(raw)
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                         for err in e.errors())
        return [_failed(rid, rel, kind, f"request file is invalid: {errs}")]
    if not ID_RE.match(rid) or rid != (preq.id if kind == "preset" else areq.id):
        return [_failed(rid, rel, kind, "request id must be letters, digits, '.', '_' or "
                        "'-' (at most 100 characters)")]
    provider = preq.provider if kind == "preset" else areq.provider
    if provider is not None and provider not in PROVIDERS:
        return [_failed(rid, rel, kind, f"unknown provider {provider!r} (use one of "
                        f"{', '.join(PROVIDERS)})")]

    if kind == "application":
        notices = []
        if areq.cover_letter:
            notices.append("Cover letters are not built yet (Phase 4); only the resumes "
                           "were made.")
        return [Job(request_id=rid, run_id=rid, request_path=rel, posting=areq.posting.text,
                    company=areq.company, position=areq.position, provider=areq.provider,
                    model=areq.model, note=areq.note, notices=notices,
                    result=RunResult(id=rid, status="failed", kind="application"))]

    presets = load_presets(data_dir).presets
    if preq.presets == "all":
        chosen = presets
    elif preq.presets == "stale":
        chosen = [p for p in presets if preset_status(data_dir, p) != "up to date"]
    else:
        known = {p.id for p in presets}
        unknown = [n for n in preq.presets if n not in known]
        if unknown:
            return [_failed(rid, rel, "preset", f"unknown preset(s): {', '.join(unknown)} "
                            f"(defined: {', '.join(sorted(known))})")]
        chosen = [p for p in presets if p.id in preq.presets]
    if not chosen:
        # Nothing to build is a success, not a failure: write a result that says so.
        return [Job(request_id=rid, run_id=rid, request_path=rel, kind="preset",
                    stage_done="compile",
                    result=RunResult(id=rid, status="done", kind="preset",
                                     notices=["Every preset is up to date; nothing was "
                                              "built."]))]
    return [Job(request_id=rid, run_id=f"{rid}--{p.id}", request_path=rel, kind="preset",
                preset_id=p.id, provider=preq.provider, model=preq.model,
                result=RunResult(id=rid, status="failed", kind="preset"))
            for p in chosen]


def start(data_dir: Path, work: Path, paths: list[Path] | None = None) -> Queue:
    """Queue the given request files, or every pending one."""
    data_dir = data_dir.resolve()
    todo = [(p if p.is_absolute() else data_dir / p).resolve() for p in paths or []]
    for p in todo:
        if not p.is_relative_to(data_dir / "requests") or not p.is_file():
            raise FileNotFoundError(f"not a request file under requests/: {p}")
    q = Queue(jobs=[j for p in todo or pending_requests(data_dir)
                    for j in jobs_for(data_dir, p)])
    save_queue(work, q)
    return q


# ---------------------------------------------------------------------------------------
# stages


def _response_to_dict(r: LLMResponse) -> dict[str, object]:
    return asdict(r)


def _response_from_dict(d: dict[str, object]) -> LLMResponse:
    u = d["usage"]
    assert isinstance(u, dict)
    return LLMResponse(text=str(d["text"]), usage=Usage(**u), provider=str(d["provider"]),
                       model=str(d["model"]), cost_usd=float(d["cost_usd"]))  # type: ignore[arg-type]


def _request(data_dir: Path, job: Job) -> RunRequest:
    preset = None
    if job.preset_id is not None:
        preset = next(p for p in load_presets(data_dir).presets if p.id == job.preset_id)
    return RunRequest(kind="preset" if preset else "application", request_id=job.run_id,
                      posting=job.posting, company=job.company, position=job.position,
                      provider=job.provider, model=job.model, note=job.note, preset=preset)


def _prefixed(log: Callable[[str], None], label: str) -> Callable[[str], None]:
    return lambda m: log(f"[{label}] {m}")


def run_queue_stage(data_dir: Path, work: Path, stage: Stage, *,
                    providers: dict[str, Provider] | None = None,
                    log: Callable[[str], None] = print) -> bool:
    """Run one stage for every job still alive. Returns False if any job failed here."""
    q = load_queue(work)
    config = load_config(data_dir)
    previous = None if stage == STAGES[0] else STAGES[STAGES.index(stage) - 1]
    ok = True
    for job in q.jobs:
        if job.failed or job.stage_done != previous:
            continue
        label = job.preset_id or job.request_id
        log(f"[{label}] {stage}")
        req = _request(data_dir, job)
        router = Router(config, providers or default_providers(config),
                        Ledger(data_dir, job.run_id, req.kind), repair_prompt,
                        first=job.provider,
                        notices=list(job.notices),
                        responses=[_response_from_dict(r) for r in job.responses])
        state = RunState(analysis=job.analysis, tailoring=job.tailoring,
                         raw_tailoring=job.raw_tailoring, repaired=list(job.repaired))
        result = job.result
        try:
            run_stage(stage, data_dir, config, req, router, state, result, None,
                      _prefixed(log, label))
            job.stage_done = stage
            if stage == STAGES[-1]:
                result.status = "done"
        except Exception as e:  # every failure becomes a readable result
            job.failed = True
            ok = False
            result.error = describe(e)
            log(f"[{label}] FAILED: {result.error}")
        finish_result(result, router)
        job.notices = router.notices
        job.responses = [_response_to_dict(r) for r in router.responses]
        job.analysis, job.tailoring = state.analysis, state.tailoring
        job.raw_tailoring, job.repaired = state.raw_tailoring, state.repaired
        save_queue(work, q)  # after every job, so a crash keeps what is done
    return ok


# ---------------------------------------------------------------------------------------
# finish


def finish(data_dir: Path, work: Path) -> list[RunResult]:
    """Write results/<id>.json for every queued request and return those results."""
    q = load_queue(work)
    by_request: dict[str, list[Job]] = {}
    for job in q.jobs:
        if not job.failed and job.stage_done != STAGES[-1]:
            # The workflow stopped (timeout or cancel) before this job finished.
            job.failed = True
            stopped = job.stage_done and STAGES[STAGES.index(job.stage_done) + 1]
            job.result.status = "failed"
            job.result.error = (f"the workflow stopped during the {stopped or STAGES[0]} "
                                "step; submit the request again")
        by_request.setdefault(job.request_id, []).append(job)
    results = []
    for rid, jobs in by_request.items():
        if len(jobs) == 1 and jobs[0].preset_id is None:
            res = jobs[0].result
        else:
            runs = [j.result.model_copy(update={"id": j.preset_id or j.run_id})
                    for j in jobs]
            failed = [r for r in runs if r.status != "done"]
            res = RunResult(
                id=rid, kind="preset", status="failed" if failed else "done",
                cost_usd=round(sum(r.cost_usd for r in runs), 6),
                provider=runs[-1].provider, model=runs[-1].model,
                notices=[n for r in runs for n in r.notices], runs=runs,
                error="; ".join(f"{r.id}: {r.error}" for r in failed) or None,
            )
        write_result(data_dir, res)
        results.append(res)
    return results


def commit_message(results: list[RunResult]) -> str:
    """`tailor: ABC Firm - Data Scientist` (PROMPT.md §8), one clause per request."""
    parts = []
    for r in results:
        if r.kind == "preset":
            built = [x.id for x in r.runs if x.status == "done"]
            what = (f"presets {', '.join(built)}" if built
                    else "presets (nothing to build)" if r.status == "done" else "presets")
        else:
            what = (r.folder or r.id).removeprefix("applications/")
        parts.append(what if r.status == "done" else f"{what} (failed)")
    return "tailor: " + "; ".join(parts) if parts else "tailor: nothing to do"


def summary_markdown(results: list[RunResult]) -> str:
    """For the Actions job summary. Names, status and cost only: never resume content."""
    lines = ["| Request | Status | Provider | Cost |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.folder or r.id} | {r.status} | {r.provider or '-'} | "
                     f"${r.cost_usd:.4f} |")
    for r in results:
        if r.error:
            lines.append(f"\n**{r.id} failed:** {r.error.splitlines()[0]}")
    return "\n".join(lines) + "\n"
