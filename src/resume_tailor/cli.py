"""`tailor` command line (PROMPT.md §7)."""

from __future__ import annotations

import argparse
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
from .ledger import now_utc
from .naming import default_out_dir
from .pipeline import RunRequest, run
from .presets import changed_inputs, read_manifest, status
from .render import render_all
from .text import slug_ascii


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines); existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
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
    posting = None if a.dry_run and not a.posting else read_posting(a.posting)
    req = RunRequest(
        kind="application", request_id=request_id(a.company), posting=posting,
        company=a.company, position=a.position, provider=a.provider, model=a.model,
        note=a.note, dry_run=a.dry_run, fixture_dir=Path(a.fixtures) if a.fixtures else None,
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

    a = ap.parse_args(argv)
    if a.cmd == "run" and not a.posting and not a.dry_run:
        ap.error("run needs --posting (or --dry-run)")
    rc: int = a.fn(a)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
