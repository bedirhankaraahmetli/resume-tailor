"""The pipeline (PROMPT.md §5): analyze → tailor → guard → render → fit → check → write.

Applications and preset builds run the same code. A preset differs only in that its
`position` and `focus` stand in for a posting analysis, its outputs go to `presets/`, and
it is not logged in `applications.csv` (its cost still goes to `usage.csv`).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import __version__
from .build import PdfInfo, compile_pdf, map_overflow, measure, prepare
from .catalog import Catalog, build_catalog
from .checks import ats_check, keyword_report
from .config import Config, Preset, load_config
from .fit import fit
from .guard import GuardResult, check, check_letter
from .ledger import Ledger, append_application, now_utc, update_application
from .letter import clean_letter, prepare_letter, render_letter
from .llm_input import PROMPT_VERSION, analyze_call, letter_call, repair_prompt, tailor_call
from .models import Analysis, CoverLetter, RunResult, Tailoring
from .naming import folder_name, letter_names, pdf_names, unique_folder
from .providers.anthropic_provider import AnthropicProvider
from .providers.base import LLMCall, Provider, ProviderError
from .providers.claude_code import ClaudeCodeProvider
from .providers.gemini import GeminiProvider
from .render import render_all
from .report import ReportData, render_report
from .router import Router


class RunFailed(RuntimeError):
    pass


Stage = Literal["analyze", "tailor", "compile"]


@dataclass
class Previous:
    """An earlier application that a regenerate rebuilds in place."""

    request_id: str
    folder: str  # under applications/
    posting: str
    analysis: Analysis


def load_previous(data_dir: Path, request_id: str) -> Previous:
    """The earlier run's folder, posting and analysis, from its result and `_build/`.

    Reusing the analysis skips one LLM call and keeps the company, position and folder
    exactly as they were, so the regenerate replaces that application instead of adding a
    second one.
    """
    try:
        prev = RunResult.model_validate_json(
            (data_dir / "results" / f"{request_id}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RunFailed(f"cannot regenerate {request_id}: it has no result") from None
    if prev.kind != "application" or prev.status != "done" or not prev.folder:
        raise RunFailed(f"cannot regenerate {request_id}: only a finished application can "
                        "be regenerated")
    top, _, folder = prev.folder.partition("/")
    build = data_dir / "applications" / folder / "_build"
    if top != "applications" or not folder or "/" in folder or not build.is_dir():
        raise RunFailed(f"cannot regenerate {request_id}: its folder {prev.folder} is missing")
    try:
        posting = (build / "posting.txt").read_text(encoding="utf-8")
        saved = json.loads((build / "llm-response.json").read_text(encoding="utf-8"))
        analysis = Analysis.model_validate(saved["analysis"])
    except (OSError, ValueError, KeyError) as e:
        raise RunFailed(f"cannot regenerate {request_id}: its saved posting or analysis "
                        f"is unreadable ({e})") from None
    return Previous(request_id=request_id, folder=folder, posting=posting, analysis=analysis)


@dataclass
class RunRequest:
    kind: Literal["application", "preset"]
    request_id: str
    posting: str | None = None
    company: str | None = None
    position: str | None = None
    provider: str | None = None
    model: str | None = None
    note: str | None = None
    preset: Preset | None = None
    previous: Previous | None = None
    # Cover letter languages, () for none: ("en",), ("tr",) or ("en", "tr").
    cover_letter: tuple[str, ...] = ()
    dry_run: bool = False
    fixture_dir: Path | None = None


def default_providers(config: Config) -> dict[str, Provider]:
    return {
        "anthropic": AnthropicProvider(config),
        "claude-code": ClaudeCodeProvider(config),
        "gemini": GeminiProvider(config),
    }


def _load_fixture(req: RunRequest, data_dir: Path) -> tuple[Analysis, Tailoring]:
    d = req.fixture_dir or data_dir / "fixtures"
    try:
        a = Analysis.model_validate_json((d / "analysis.json").read_text(encoding="utf-8"))
        t = Tailoring.model_validate_json((d / "tailoring.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RunFailed(f"--dry-run needs recorded fixtures in {d} (analysis.json, "
                        "tailoring.json)") from e
    return a, t


def preset_analysis(preset: Preset) -> Analysis:
    return Analysis(company=None, position=preset.position, posting_language="en",
                    seniority="unspecified", must_have=[], nice_to_have=[], keywords=[])


STAGES: tuple[Stage, ...] = ("analyze", "tailor", "compile")


@dataclass
class RunState:
    """Everything one stage hands to the next. In `tailor run` it lives in memory; in
    GitHub Actions each stage is its own step (so the web app can show which one is
    running) and the state goes through a checkpoint file between them."""

    analysis: Analysis | None = None
    tailoring: Tailoring | None = None
    raw_tailoring: str | None = None
    repaired: list[str] = field(default_factory=list)
    letter: CoverLetter | None = None
    # Every letter answer and what the guard said about it, saved with the outputs so a
    # skipped letter can be diagnosed.
    letter_attempts: list[dict[str, object]] = field(default_factory=list)


def run(data_dir: Path, req: RunRequest, *, out_dir: Path | None,
        providers: dict[str, Provider] | None = None,
        log: Callable[[str], None] = print) -> RunResult:
    config = load_config(data_dir)
    result = RunResult(id=req.request_id, status="failed", kind=req.kind)
    ledger = Ledger(data_dir, req.request_id, req.kind)
    router = Router(config, providers or default_providers(config), ledger, repair_prompt,
                    first=req.provider)
    state = RunState()
    try:
        for stage in STAGES:
            run_stage(stage, data_dir, config, req, router, state, result, out_dir, log)
        result.status = "done"
    except Exception as e:  # every failure becomes a readable result, never a traceback
        result.error = describe(e)
        log(f"FAILED: {result.error}")
    finally:
        finish_result(result, router)
        write_result(data_dir, result)
    return result


def run_stage(stage: Stage, data_dir: Path, config: Config, req: RunRequest, router: Router,
              state: RunState, result: RunResult, out_dir: Path | None,
              log: Callable[[str], None]) -> None:
    """One stage. Raises on failure; the caller turns the exception into a result."""
    if stage == "analyze":
        _analyze(data_dir, config, req, router, state, log)
    elif stage == "tailor":
        _tailor(data_dir, config, req, router, state, log)
    else:
        _compile(data_dir, config, req, router, state, result, out_dir, log)


def finish_result(result: RunResult, router: Router) -> None:
    result.notices = list(dict.fromkeys([*result.notices, *router.notices]))
    result.cost_usd = router.total_cost
    if router.responses:
        result.provider = router.responses[-1].provider
        result.model = router.responses[-1].model


def write_result(data_dir: Path, result: RunResult) -> None:
    results_dir = data_dir / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{result.id}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")


def describe(e: Exception) -> str:
    if isinstance(e, RunFailed | ProviderError):
        return str(e)
    return f"{type(e).__name__}: {e}"


def _analyze(data_dir: Path, config: Config, req: RunRequest, router: Router,
             state: RunState, log: Callable[[str], None]) -> None:
    log("analyzing posting…")
    if req.kind == "preset":
        assert req.preset is not None
        analysis = preset_analysis(req.preset)
    elif req.previous is not None:
        log("reusing the earlier run's posting analysis…")
        analysis = req.previous.analysis.model_copy(deep=True)
    elif req.dry_run:
        analysis, _ = _load_fixture(req, data_dir)
    else:
        if not req.posting or not req.posting.strip():
            raise RunFailed("the posting is empty")
        analysis, _, _ = router.run(analyze_call(config, req.posting, None),
                                    Analysis.model_validate_json)
    if req.company:
        analysis.company = req.company
    if req.position:
        analysis.position = req.position
    state.analysis = analysis


def _tailor(data_dir: Path, config: Config, req: RunRequest, router: Router, state: RunState,
            log: Callable[[str], None]) -> None:
    """Tailoring plus the fact guard, with one repair round on the same provider."""
    assert state.analysis is not None
    cat = build_catalog(data_dir, config)
    log("tailoring…")
    call: LLMCall | None = None
    provider: Provider | None = None
    if req.dry_run:
        _, tailoring = _load_fixture(req, data_dir)
    else:
        call = tailor_call(cat, analysis=state.analysis, posting=req.posting, note=req.note,
                           preset=req.preset, model=req.model)
        tailoring, resp, provider = router.run(call, Tailoring.model_validate_json)
        state.raw_tailoring = resp.text
    g = check(cat, tailoring)
    if not g.ok and call is not None and provider is not None:
        log(f"fact guard: {len(g.violations)} problem(s); asking for one repair…")
        state.repaired = [str(v) for v in g.violations]
        repair = LLMCall("repair", "tailor", call.system,
                         repair_prompt(call.user, tailoring.model_dump_json(),
                                       [str(v) for v in g.violations]),
                         Tailoring, call.model_override)
        tailoring, resp = router.call_on(provider, repair, Tailoring.model_validate_json)
        state.raw_tailoring = resp.text
        g = check(cat, tailoring)
    if not g.ok:
        raise RunFailed("fact guard failed after one repair round:\n"
                        + "\n".join(f"  - {v}" for v in g.violations))
    state.tailoring = tailoring
    if req.cover_letter and req.kind == "application":
        _letter(data_dir, cat, req, router, state, log)


def _letter(data_dir: Path, cat: Catalog, req: RunRequest, router: Router, state: RunState,
            log: Callable[[str], None]) -> None:
    """The cover letter body, through its own fact guard with one repair round.

    Optional by nature: any failure is a notice and the resumes are still delivered.
    """
    assert state.analysis is not None and state.tailoring is not None
    langs = req.cover_letter
    log(f"writing the cover letter ({', '.join(langs)})…")
    try:
        if req.dry_run:
            d = req.fixture_dir or data_dir / "fixtures"
            letter = clean_letter(CoverLetter.model_validate_json(
                (d / "letter.json").read_text(encoding="utf-8")))
            g = check_letter(cat, letter, langs, req.posting)
        else:
            assert req.posting is not None
            call = letter_call(cat, analysis=state.analysis, posting=req.posting,
                               tailoring=state.tailoring, note=req.note, langs=langs,
                               model=req.model)
            letter, resp, provider = router.run(call, CoverLetter.model_validate_json)
            letter = clean_letter(letter)
            g = check_letter(cat, letter, langs, req.posting)
            state.letter_attempts.append(_attempt(letter, g))
            if not g.ok:
                log(f"letter guard: {len(g.violations)} problem(s); asking for one repair…")
                errors = [str(v) for v in g.violations]
                if any(v.code == "number" for v in g.violations):
                    errors.append("For a number that is not in the cited sources: delete the "
                                  "number and the claim it makes. Citing another source does "
                                  "not help unless that source's own text contains it.")
                repair = LLMCall("repair", "tailor", call.system,
                                 repair_prompt(call.user, resp.text, errors),
                                 CoverLetter, call.model_override)
                letter, _ = router.call_on(provider, repair, CoverLetter.model_validate_json)
                letter = clean_letter(letter)
                g = check_letter(cat, letter, langs, req.posting)
                state.letter_attempts.append(_attempt(letter, g))
    except Exception as e:  # never lose the resumes over the optional letter
        router.notices.append(f"Cover letter skipped: {describe(e)}")
        return
    if not g.ok:
        router.notices.append("Cover letter skipped: the fact guard still failed after one "
                              "repair round: " + "; ".join(str(v) for v in g.violations))
        return
    state.letter = letter


def _compile(data_dir: Path, config: Config, req: RunRequest, router: Router,
             state: RunState, result: RunResult, out_dir: Path | None,
             log: Callable[[str], None]) -> None:
    """Render, compile and fit both languages together, run the checks, write outputs."""
    analysis, tailoring = state.analysis, state.tailoring
    assert analysis is not None and tailoring is not None
    cat = build_catalog(data_dir, config)
    g = check(cat, tailoring)  # deterministic, so recomputing it here is free of drift
    log("compiling and fitting to one page…")
    work = Path(tempfile.mkdtemp(prefix="rt-build-"))
    try:
        def compile_fn(lang: str, t: Tailoring) -> PdfInfo:
            d = work / lang
            rendered = render_all(cat, t, lang)
            prepare(data_dir / "base" / lang, rendered, d)
            return map_overflow(measure(compile_pdf(d)), rendered["src/projects.tex"],
                                [p.id for p in t.projects])

        r = config.resume
        fitted = fit(tailoring, compile_fn, min_projects=min(r.min_projects,
                     len(cat.usable_project_ids())), min_courses=r.min_courses,
                     fill_threshold=r.fill_threshold)
        final = fitted.tailoring
        # The last compile may have been a reverted reserve trial: build the final state.
        info = {lang: compile_fn(lang, final) for lang in ("en", "tr")}
        if any(i.pages != 1 or i.overflow_projects for i in info.values()):
            raise RunFailed("final build is not one page or has a heading wider than the page")

        keywords = None
        if req.kind == "application":
            r_cfg = config.resume
            keywords = keyword_report(
                analysis, info["en"].text, cat.evidence_chunks(), tr_text=info["tr"].text,
                tr_names={**r_cfg.skill_names_tr, **r_cfg.course_names_tr})
        # Say what the first answer got wrong: it shows how much the guard is doing.
        warnings = [f"fact guard caught (fixed by the repair round): {x}"
                    for x in state.repaired]
        warnings += g.warnings
        for lang in ("en", "tr"):
            # Must-have keywords are checked on the English page only. Both pages carry the
            # same selection (T8), so a term missing from the Turkish one is a vocabulary
            # difference ("oyun geliştirme"), not missing content, and the posting analysis
            # rarely supplies the Turkish form to match it against.
            must = keywords.must_have_with_evidence if keywords and lang == "en" else None
            ev = keywords.must_evidence if keywords and lang == "en" else None
            ats = ats_check(info[lang].text, names=config.owner.names, evidence=ev,
                            email=config.owner.email, lang=lang, must_have=must)
            if ats.errors:
                raise RunFailed("ATS check failed: " + "; ".join(ats.errors))
            warnings += ats.warnings
        warnings += cat.warnings

        letters = _compile_letters(data_dir, config, req, analysis, state.letter, router,
                                   work, log)
        _write_outputs(data_dir, config, cat, req, analysis, tailoring, final, fitted.log,
                       info, keywords, warnings, router, result, out_dir, work,
                       state.raw_tailoring, letters, state.letter_attempts)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _attempt(letter: CoverLetter, g: GuardResult) -> dict[str, object]:
    return {"letter": letter.model_dump(), "violations": [str(v) for v in g.violations]}


def _compile_letters(data_dir: Path, config: Config, req: RunRequest, analysis: Analysis,
                     letter: CoverLetter | None, router: Router, work: Path,
                     log: Callable[[str], None]) -> dict[str, Path]:
    """One PDF per requested language. A letter that does not fit one page is dropped
    with a notice: fonts and margins are never shrunk to make it fit (T2)."""
    if letter is None:
        return {}
    log("compiling the cover letter…")
    out: dict[str, Path] = {}
    for lang in req.cover_letter:
        base = data_dir / "base" / lang
        try:
            tex = render_letter((base / "resume.tex").read_text(encoding="utf-8"), letter,
                                lang, company=analysis.company, position=analysis.position,
                                signer=config.owner.names[0], today=now_utc().date())
            d = work / f"letter-{lang}"
            prepare_letter(base, tex, d)
            pdf = compile_pdf(d, main="letter")
            pages = measure(pdf).pages
        except Exception as e:  # the letter is optional; the resumes are not
            router.notices.append(f"Cover letter ({lang}) skipped: {describe(e)}")
            continue
        if pages != 1:
            router.notices.append(f"Cover letter ({lang}) skipped: it ran to {pages} pages. "
                                  "Regenerate with a note asking for a shorter letter.")
            continue
        out[lang] = pdf
    return out


def _write_outputs(data_dir: Path, config: Config, cat: Catalog, req: RunRequest,
                   analysis: Analysis, proposed: Tailoring, final: Tailoring,
                   fit_log: list[str], info: dict[str, PdfInfo], keywords: object,
                   warnings: list[str], router: Router, result: RunResult,
                   out_dir: Path | None, work: Path, raw: str | None,
                   letters: dict[str, Path] | None = None,
                   letter_attempts: list[dict[str, object]] | None = None) -> None:
    from .checks import KeywordReport

    letters = letters or {}

    position = analysis.position
    names = pdf_names(config.owner.slug, position)
    if req.kind == "preset":
        assert req.preset is not None
        folder = req.preset.folder
        dest = data_dir / "presets" / folder
        copy_to = out_dir / "_Presets" / folder if out_dir else None
        title = f"Preset — {folder}"
    elif req.previous is not None:
        folder = req.previous.folder
        dest = data_dir / "applications" / folder
        copy_to = out_dir / folder if out_dir else None
        title = f"Match report — {folder}"
    else:
        folder = unique_folder(folder_name(analysis.company, position),
                               data_dir / "applications", *( [out_dir] if out_dir else []))
        dest = data_dir / "applications" / folder
        copy_to = out_dir / folder if out_dir else None
        title = f"Match report — {folder}"
    if dest.exists() and (req.kind == "preset" or req.previous is not None):
        # A rebuild replaces the folder; the earlier version stays in git history.
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    build = dest / "_build"
    for lang in ("en", "tr"):
        (build / lang / "src").mkdir(parents=True, exist_ok=True)
        for f in (work / lang / "src").glob("*.tex"):
            shutil.copyfile(f, build / lang / "src" / f.name)
        shutil.copyfile(work / lang / "resume.pdf", dest / names[lang])
    lnames = letter_names(config.owner.slug, position)
    for lang, pdf in letters.items():
        shutil.copyfile(pdf, dest / lnames[lang])
    if req.posting:
        (build / "posting.txt").write_text(req.posting, encoding="utf-8")
    (build / "llm-response.json").write_text(json.dumps({
        "analysis": analysis.model_dump(),
        "tailoring_proposed": json.loads(raw) if raw else proposed.model_dump(),
        "tailoring_final": final.model_dump(),
        "fit_log": fit_log,
        **({"letter_attempts": letter_attempts} if letter_attempts else {}),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    kr = keywords if isinstance(keywords, KeywordReport) else None
    report = render_report(cat, ReportData(
        title=title, kind=req.kind,
        generated=now_utc().strftime("%Y-%m-%d %H:%M UTC"),
        analysis=analysis, tailoring=final, keywords=kr, responses=router.responses,
        fit_log=fit_log, empty={k: v.empty_fraction for k, v in info.items()},
        warnings=warnings, notices=router.notices, prompt_version=PROMPT_VERSION,
    ))
    (dest / "match-report.md").write_text(report, encoding="utf-8")

    if copy_to is not None:
        copy_to.mkdir(parents=True, exist_ok=True)
        for fname in (names["en"], names["tr"], "match-report.md",
                      *(lnames[lang] for lang in letters)):
            shutil.copyfile(dest / fname, copy_to / fname)

    rel = dest.relative_to(data_dir).as_posix()
    result.folder = rel
    result.files = {"en": f"{rel}/{names['en']}", "tr": f"{rel}/{names['tr']}",
                    "report": f"{rel}/match-report.md",
                    **{f"cover_{lang}": f"{rel}/{lnames[lang]}" for lang in letters}}
    result.match_pct = kr.match_pct if kr else None
    result.notices = list(warnings)
    if letters:
        result.notices.append(f"Cover letter written ({', '.join(letters)}).")
    if router.responses:
        last = router.responses[-1]
        provider, model = last.provider, last.model
    else:
        provider, model = "dry-run", "fixture"
    match = "" if result.match_pct is None else str(result.match_pct)
    if req.previous is not None and update_application(
            data_dir, req.previous.request_id, provider=provider, model=model,
            added_cost=router.total_cost, match_pct=match, request_id_new=req.request_id):
        result.notices.append(f"Regenerated {folder}: its files were replaced, and its "
                              "History row was updated (status kept, cost added).")
    elif req.kind == "application":
        append_application(data_dir, {
            "date": now_utc().strftime("%Y-%m-%d"), "company": analysis.company or "",
            "position": position, "folder": folder, "provider": provider, "model": model,
            "cost_usd": f"{router.total_cost:.4f}", "match_pct": match,
            "status": "generated", "source": "tailored", "request_id": req.request_id,
        })
    if req.kind == "preset":
        from .presets import write_manifest

        assert req.preset is not None
        write_manifest(data_dir, req.preset, provider, model, router.total_cost,
                       {"en": names["en"], "tr": names["tr"]}, __version__)
