"""Compile with pdfLaTeX and measure the result.

pdfLaTeX only (never XeLaTeX/LuaLaTeX/Tectonic): the base preamble uses pdfTeX
primitives (`\\pdfgentounicode`, `\\pdfglyphtounicode`) that keep the PDF text layer clean
for ATS parsers.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from .base import FIXED_FILES

# Text block of the base layout: letterpaper with fullpage[empty] and the base's
# -0.5in top / +1in textheight adjustments leaves 0.5in (36pt) below the last baseline.
BOTTOM_MARGIN_PT = 36.0


class CompileError(RuntimeError):
    pass


@dataclass
class PdfInfo:
    pages: int
    empty_fraction: float
    text: str
    # Lines of src/projects.tex whose heading row is wider than the page. A too-long
    # "Title | stack" pushes the link into the margin; the page count cannot see it.
    overfull_project_lines: list[int] = field(default_factory=list)
    # Project ids those lines belong to (filled in by the caller, which knows the layout).
    overflow_projects: list[str] = field(default_factory=list)


_OPEN_RE = re.compile(r"\(\./(src/[\w-]+\.tex)")
_OVERFULL_RE = re.compile(r"Overfull \\hbox \(([\d.]+)pt too wide\) in alignment at lines (\d+)--")


def overfull_lines(log: str, src: str = "src/projects.tex", min_pt: float = 1.0) -> list[int]:
    """Alignment rows wider than the text block, in `src`, from a pdfLaTeX log."""
    opens = [(m.start(), m.group(1)) for m in _OPEN_RE.finditer(log)]
    lines = []
    for m in _OVERFULL_RE.finditer(log):
        current = next((f for pos, f in reversed(opens) if pos < m.start()), None)
        if current == src and float(m.group(1)) >= min_pt:
            lines.append(int(m.group(2)))
    return lines


def find_pdflatex() -> str | None:
    found = shutil.which("pdflatex")
    if found:
        return found
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "TinyTeX/bin/windows/pdflatex.exe",
        Path.home() / ".TinyTeX/bin/x86_64-linux/pdflatex",
        Path.home() / "Library/TinyTeX/bin/universal-darwin/pdflatex",
    ]
    return next((str(c) for c in candidates if c.exists()), None)


def prepare(base_dir: Path, rendered: dict[str, str], build_dir: Path) -> None:
    """Copy the untouchable files verbatim and write the tailored src files."""
    (build_dir / "src").mkdir(parents=True, exist_ok=True)
    for rel in FIXED_FILES:
        shutil.copyfile(base_dir / rel, build_dir / rel)
    for rel, content in rendered.items():
        (build_dir / rel).write_text(content, encoding="utf-8", newline="\n")


def compile_pdf(build_dir: Path, pdflatex: str | None = None, main: str = "resume") -> Path:
    exe = pdflatex or find_pdflatex()
    if exe is None:
        raise CompileError("pdflatex not found. Install TinyTeX (see README) or add it to PATH.")
    # One pass is enough: the resume has no references, TOC or page-number fields.
    proc = subprocess.run(
        [exe, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", f"{main}.tex"],
        cwd=build_dir, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180,
    )
    pdf = build_dir / f"{main}.pdf"
    if proc.returncode != 0 or not pdf.exists():
        # Error lines only: the full log echoes resume content, which CI must not print.
        errors = [ln for ln in proc.stdout.splitlines() if ln.startswith("!") or ":error" in ln
                  or re.match(r"^\S+\.tex:\d+:", ln)]
        raise CompileError("pdflatex failed: " + (" | ".join(errors[:5]) or "see build log"))
    return pdf


def measure(pdf: Path) -> PdfInfo:
    reader = PdfReader(pdf)
    page = reader.pages[0]
    ys: list[float] = []

    def visit(text: str, cm: list[float], tm: list[float], _fd: object, _fs: float) -> None:
        if text.strip():
            ys.append(tm[5] * cm[3] + cm[5])

    text = page.extract_text(visitor_text=visit)
    full = "\n".join(p.extract_text() or "" for p in reader.pages)
    log_path = pdf.with_suffix(".log")
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    over = overfull_lines(log)
    if not ys:
        return PdfInfo(len(reader.pages), 1.0, full, over)
    top = max(ys)
    usable = max(top - BOTTOM_MARGIN_PT, 1.0)
    empty = max(0.0, (min(ys) - BOTTOM_MARGIN_PT) / usable)
    return PdfInfo(len(reader.pages), round(empty, 4), full or text, over)


def project_heading_lines(projects_tex: str) -> list[int]:
    """1-based line numbers of each \\resumeProjectHeading, in order."""
    return [i for i, line in enumerate(projects_tex.split("\n"), start=1)
            if line.lstrip().startswith(r"\resumeProjectHeading")]


def map_overflow(info: PdfInfo, projects_tex: str, project_ids: list[str]) -> PdfInfo:
    starts = project_heading_lines(projects_tex)
    ids: list[str] = []
    for line in info.overfull_project_lines:
        idx = max((k for k, s in enumerate(starts) if s <= line), default=None)
        if idx is not None and idx < len(project_ids) and project_ids[idx] not in ids:
            ids.append(project_ids[idx])
    info.overflow_projects = ids
    return info
