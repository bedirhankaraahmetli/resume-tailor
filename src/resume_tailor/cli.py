"""`tailor` command line (PROMPT.md §7)."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader

from . import __version__
from .build import compile_pdf, find_pdflatex, measure, prepare
from .catalog import build_catalog
from .config import load_config, load_presets
from .guard import check as guard_check
from .identity import identity_tailoring, normalize_tex
from .keys import (
    PROVIDER_VARS,
    KeyError_,
    check_live,
    mask,
    push_to_github,
    read_env,
    validate_value,
    write_env,
)
from .keys import status as keys_status
from .ledger import now_utc
from .naming import default_out_dir
from .pipeline import RunFailed, RunRequest, load_previous, run
from .presets import changed_inputs, read_manifest, status
from .render import render_all
from .text import slug_ascii


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines); existing environment variables win."""
    if not path.exists():
        return
    # utf-8-sig: Notepad may save .env with a BOM, which would corrupt the first key name.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_posting(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    p = Path(arg)
    if p.suffix.lower() == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(p).pages)
    return p.read_text(encoding="utf-8")


def request_id(label: str | None) -> str:
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    slug = slug_ascii(label or "posting").lower()[:40] or "posting"
    return f"{stamp}-{slug}"


def _out(arg: str | None) -> Path | None:
    if arg is None:
        return default_out_dir()
    if arg.lower() == "none":
        return None
    return Path(arg)


def cmd_run(a: argparse.Namespace) -> int:
    data = Path(a.data_dir)
    if a.regenerate:
        return _regenerate(data, a)
    posting = None if a.dry_run and not a.posting else read_posting(a.posting)
    req = RunRequest(
        kind="application", request_id=request_id(a.company), posting=posting,
        company=a.company, position=a.position, provider=a.provider, model=a.model,
        note=a.note, dry_run=a.dry_run, fixture_dir=Path(a.fixtures) if a.fixtures else None,
    )
    res = run(data, req, out_dir=_out(a.out))
    _print_result(res)
    return 0 if res.status == "done" else 1


def _regenerate(data: Path, a: argparse.Namespace) -> int:
    if a.posting or a.company or a.position or a.dry_run:
        print("--regenerate reuses the earlier run's posting, company and position; "
              "give only --note (and optionally --provider or --model).", file=sys.stderr)
        return 2
    try:
        prev = load_previous(data, a.regenerate)
    except RunFailed as e:
        print(str(e), file=sys.stderr)
        return 1
    req = RunRequest(
        kind="application", request_id=request_id(prev.analysis.company),
        posting=prev.posting, provider=a.provider, model=a.model, note=a.note, previous=prev,
    )
    res = run(data, req, out_dir=_out(a.out))
    _print_result(res)
    return 0 if res.status == "done" else 1


def _print_result(res: object) -> None:
    from .models import RunResult

    assert isinstance(res, RunResult)
    if res.status == "done":
        print(f"done: {res.folder}")
        for k, v in res.files.items():
            print(f"  {k}: {v}")
        if res.match_pct is not None:
            print(f"  match: {res.match_pct}%")
    print(f"  provider: {res.provider or '-'} ({res.model or '-'}) · cost ${res.cost_usd:.4f}")
    for n in res.notices:
        print(f"  note: {n}")
    if res.error:
        print(f"error: {res.error}", file=sys.stderr)


def cmd_check(a: argparse.Namespace) -> int:
    data = Path(a.data_dir)
    ok = True
    cfg = load_config(data)
    cat = build_catalog(data, cfg)
    print(f"inventory: {len(cat.experience_ids)} experience, {len(cat.project_ids)} projects "
          f"({len(cat.usable_project_ids())} usable), {len(cat.certificates)} certificates, "
          f"{len(cat.skills)} skills")
    for w in cat.warnings:
        print(f"  warning: {w}")
    ident = identity_tailoring(cat)
    for lang in ("en", "tr"):
        for rel, txt in render_all(cat, ident, lang).items():
            orig = (data / "base" / lang / rel).read_text(encoding="utf-8")
            if normalize_tex(orig) != normalize_tex(txt):
                ok = False
                print(f"  FAIL identity round-trip: base/{lang}/{rel}")
    print("renderer: identity round-trip " + ("ok" if ok else "FAILED"))
    g = guard_check(cat, ident)
    for v in g.violations:
        print(f"  guard: {v}")
    print("fact guard on base content: " + ("ok" if g.ok else "FAILED"))
    ok = ok and g.ok
    if find_pdflatex() is None:
        print("pdflatex: not found (skipping test compile)")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            for lang in ("en", "tr"):
                d = Path(tmp) / lang
                prepare(data / "base" / lang, render_all(cat, ident, lang), d)
                info = measure(compile_pdf(d))
                print(f"compile {lang}: {info.pages} page(s), {info.empty_fraction:.0%} empty")
                ok = ok and info.pages == 1
    presets = load_presets(data).presets
    print(f"presets: {len(presets)} defined")
    return 0 if ok else 1


def cmd_preset_list(a: argparse.Namespace) -> int:
    data = Path(a.data_dir)
    for p in load_presets(data).presets:
        st = status(data, p)
        m = read_manifest(data, p)
        extra = f" · built {m.built_at} · ${m.cost_usd:.4f} · {m.model}" if m else ""
        print(f"{p.id:20} {st:12} {p.folder}{extra}")
        if st == "outdated":
            print("    changed: " + ", ".join(changed_inputs(data, p)))
    return 0


def cmd_preset_build(a: argparse.Namespace) -> int:
    data = Path(a.data_dir)
    presets = load_presets(data).presets
    if a.all:
        chosen = presets
    elif a.stale:
        chosen = [p for p in presets if status(data, p) != "up to date"]
    else:
        unknown = [n for n in a.names if n not in {p.id for p in presets}]
        if unknown or not a.names:
            print(f"name presets to build ({', '.join(p.id for p in presets)}), or use "
                  "--all / --stale", file=sys.stderr)
            return 2
        chosen = [p for p in presets if p.id in a.names]
    if not chosen:
        print("nothing to build: every preset is up to date")
        return 0
    rc = 0
    for p in chosen:
        print(f"== preset {p.id}")
        req = RunRequest(kind="preset", request_id=request_id(f"preset-{p.id}"), preset=p,
                         provider=a.provider, model=a.model, note=a.note)
        res = run(data, req, out_dir=_out(a.out))
        _print_result(res)
        rc |= 0 if res.status == "done" else 1
    return rc


def _gh_append(var: str, text: str) -> None:
    """Append to a GitHub Actions file ($GITHUB_OUTPUT, $GITHUB_STEP_SUMMARY) if set."""
    path = os.environ.get(var)
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def cmd_request_start(a: argparse.Namespace) -> int:
    from .jobs import start

    q = start(Path(a.data_dir), Path(a.work), [Path(p) for p in a.request] or None)
    requests = sorted({j.request_id for j in q.jobs})
    print(f"{len(requests)} request(s), {len(q.jobs)} run(s) queued")
    for rid in requests:
        print(f"  {rid}")
    _gh_append("GITHUB_OUTPUT", f"jobs={len(q.jobs)}\n")
    from .basepdf import status as base_status

    stale = base_status(Path(a.data_dir)) != "up to date"
    print(f"base PDFs: {'need a rebuild' if stale else 'up to date'}")
    _gh_append("GITHUB_OUTPUT", f"base={'stale' if stale else 'ok'}\n")
    return 0


def cmd_request_stage(a: argparse.Namespace) -> int:
    from .jobs import run_queue_stage

    return 0 if run_queue_stage(Path(a.data_dir), Path(a.work), a.stage) else 1


def cmd_request_finish(a: argparse.Namespace) -> int:
    from .jobs import commit_message, finish, summary_markdown

    results = finish(Path(a.data_dir), Path(a.work))
    msg = commit_message(results)
    if a.message_file:
        Path(a.message_file).write_text(msg + "\n", encoding="utf-8")
    print(msg)
    if results:
        _gh_append("GITHUB_STEP_SUMMARY", summary_markdown(results))
    return 0


def cmd_base_build(a: argparse.Namespace) -> int:
    from .basepdf import FOLDER, build, status

    data = Path(a.data_dir)
    if a.if_stale and status(data) == "up to date":
        print("base PDFs are up to date")
        return 0
    names = build(data)
    print(f"built {FOLDER}/{names['en']} and {FOLDER}/{names['tr']}")
    return 0


def cmd_init_data_repo(a: argparse.Namespace) -> int:
    from .scaffold import init_data_repo, tool_head

    ref = a.tool_ref or tool_head()
    if not ref:
        print("pass --tool-ref <commit or tag> of the tool repo to pin the workflow to",
              file=sys.stderr)
        return 2
    for line in init_data_repo(Path(a.path), tool_repo=a.tool_repo, tool_ref=ref,
                               update_workflow=a.update_workflow):
        print(line)
    return 0


def cmd_keys_list(a: argparse.Namespace) -> int:
    path = Path(a.env_file)
    print(f"keys in {path.resolve()}")
    for s in keys_status(path):
        where = {"missing": "not set", ".env": f"{s.masked}  (.env)",
                 "environment": f"{s.masked}  (environment variable)"}[s.source]
        print(f"  {s.provider:12} {s.var:24} {where}")
    return 0


def cmd_keys_set(a: argparse.Namespace) -> int:
    var = PROVIDER_VARS[a.provider]
    if a.stdin:
        value = sys.stdin.readline().strip()
    else:
        value = getpass.getpass(f"Paste the new {var} (input is hidden): ").strip()
    try:
        validate_value(var, value)
    except KeyError_ as e:
        print(f"not saved: {e}", file=sys.stderr)
        return 2
    if not a.no_check:
        ok, msg = check_live(a.provider, value)
        print(f"check: {msg}")
        if not ok:
            print("not saved. Use --no-check to save it anyway.", file=sys.stderr)
            return 1
    path = Path(a.env_file)
    write_env(path, var, value)
    os.environ[var] = value
    print(f"saved {var} = {mask(value)} to {path.resolve()}")
    if a.github:
        try:
            push_to_github(var, value, a.github)
        except KeyError_ as e:
            print(f"GitHub: {e}", file=sys.stderr)
            return 1
        print(f"GitHub: stored as Actions secret {var} in {a.github}")
    return 0


def cmd_keys_remove(a: argparse.Namespace) -> int:
    var = PROVIDER_VARS[a.provider]
    path = Path(a.env_file)
    if var not in read_env(path):
        print(f"{var} is not in {path}")
        return 0
    write_env(path, var, None)
    print(f"removed {var} from {path.resolve()}")
    return 0


def cmd_keys_check(a: argparse.Namespace) -> int:
    path = Path(a.env_file)
    values = read_env(path)
    rc = 0
    for provider, var in PROVIDER_VARS.items():
        if a.provider and provider != a.provider:
            continue
        value = values.get(var) or os.environ.get(var, "")
        if not value:
            print(f"  {provider:12} not set")
            continue
        ok, msg = check_live(provider, value)
        print(f"  {provider:12} {mask(value)}  {msg}")
        rc |= 0 if ok else 1
    return rc


def main(argv: list[str] | None = None) -> int:
    # The Windows console defaults to a legacy code page that cannot print Turkish.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    _load_dotenv(Path.cwd() / ".env")
    ap = argparse.ArgumentParser(prog="tailor", description="Tailor a LaTeX resume (EN + TR).")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="tailor both resumes to one posting")
    r.add_argument("--data-dir", required=True)
    r.add_argument("--posting", help="posting file (.txt, .md, .pdf) or - for stdin")
    r.add_argument("--company")
    r.add_argument("--position", help="overrides the title found in the posting")
    r.add_argument("--provider", choices=["anthropic", "claude-code", "gemini"])
    r.add_argument("--model", help="override the tailoring model id")
    r.add_argument("--note", help='e.g. "emphasize iOS"')
    r.add_argument("--regenerate", metavar="REQUEST_ID",
                   help="rebuild an earlier application in place, with a new --note")
    r.add_argument("--out", help="output root (default: Desktop/Job Applications; 'none' to skip)")
    r.add_argument("--dry-run", action="store_true", help="use recorded fixtures, no LLM call")
    r.add_argument("--fixtures", help="fixture directory for --dry-run")
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("check", help="validate inventory and bases, test-compile both")
    c.add_argument("--data-dir", required=True)
    c.set_defaults(fn=cmd_check)

    p = sub.add_parser("preset", help="ready-made resumes per role family")
    psub = p.add_subparsers(dest="pcmd", required=True)
    pl = psub.add_parser("list")
    pl.add_argument("--data-dir", required=True)
    pl.set_defaults(fn=cmd_preset_list)
    pb = psub.add_parser("build")
    pb.add_argument("--data-dir", required=True)
    pb.add_argument("names", nargs="*")
    g = pb.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true")
    g.add_argument("--stale", action="store_true")
    pb.add_argument("--provider", choices=["anthropic", "claude-code", "gemini"])
    pb.add_argument("--model")
    pb.add_argument("--note")
    pb.add_argument("--out")
    pb.set_defaults(fn=cmd_preset_build)

    b = sub.add_parser("base", help="the untailored base resumes as PDFs")
    bsub = b.add_subparsers(dest="bcmd", required=True)
    bb = bsub.add_parser("build", help="compile base/en and base/tr into base-pdf/")
    bb.add_argument("--data-dir", required=True)
    bb.add_argument("--if-stale", action="store_true", help="skip if base/ has not changed")
    bb.set_defaults(fn=cmd_base_build)

    i = sub.add_parser("init-data-repo", help="scaffold a private data repo")
    i.add_argument("path")
    i.add_argument("--tool-repo", default="bedirhankaraahmetli/resume-tailor",
                   help="OWNER/NAME of the public tool repo the workflow calls")
    i.add_argument("--tool-ref",
                   help="commit or tag of the tool to pin (default: this checkout's HEAD)")
    i.add_argument("--update-workflow", action="store_true",
                   help="rewrite .github/workflows/tailor.yml even if it exists")
    i.set_defaults(fn=cmd_init_data_repo)

    rq = sub.add_parser("request", help="process request files (used by GitHub Actions)")
    rsub = rq.add_subparsers(dest="rcmd", required=True)
    rs = rsub.add_parser("start", help="queue pending requests (or the given files)")
    rs.add_argument("--request", action="append", default=[],
                    help="request file (relative to the data dir); repeatable")
    rs.set_defaults(fn=cmd_request_start)
    for stage in ("analyze", "tailor", "compile"):
        st = rsub.add_parser(stage, help=f"run the {stage} stage for every queued request")
        st.set_defaults(fn=cmd_request_stage, stage=stage)
    rf = rsub.add_parser("finish", help="write results/<id>.json and the commit message")
    rf.add_argument("--message-file")
    rf.set_defaults(fn=cmd_request_finish)
    for rp in rsub.choices.values():
        rp.add_argument("--data-dir", required=True)
        rp.add_argument("--work", required=True,
                        help="checkpoint folder shared by the steps (outside the data repo)")

    k = sub.add_parser("keys", help="add, change, check or remove API keys")
    ksub = k.add_subparsers(dest="kcmd", required=True)
    providers = list(PROVIDER_VARS)
    kl = ksub.add_parser("list", help="show which keys are set (masked)")
    kl.set_defaults(fn=cmd_keys_list)
    ks = ksub.add_parser("set", help="add or replace a key (typed hidden, then verified)")
    ks.add_argument("provider", choices=providers)
    ks.add_argument("--stdin", action="store_true", help="read the key from stdin")
    ks.add_argument("--github", metavar="OWNER/REPO",
                    help="also store it as a GitHub Actions secret in this repo")
    ks.add_argument("--no-check", action="store_true", help="skip the free validity check")
    ks.set_defaults(fn=cmd_keys_set)
    kr = ksub.add_parser("remove", help="delete a key from the .env file")
    kr.add_argument("provider", choices=providers)
    kr.set_defaults(fn=cmd_keys_remove)
    kc = ksub.add_parser("check", help="verify the stored keys with a free call")
    kc.add_argument("provider", nargs="?", choices=providers)
    kc.set_defaults(fn=cmd_keys_check)
    for kp in (kl, ks, kr, kc):
        kp.add_argument("--env-file", default=".env",
                        help="file to read/write (default: .env in the current folder)")

    a = ap.parse_args(argv)
    if a.cmd == "run" and not a.posting and not a.dry_run:
        ap.error("run needs --posting (or --dry-run)")
    rc: int = a.fn(a)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
