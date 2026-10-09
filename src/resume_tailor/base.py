"""Read a base resume (`base/en` or `base/tr`) into frames and blocks.

The renderer must never change the layout, so we do not template the files from scratch:
each `src/*.tex` is split into a *frame* (section title, list start/end, spacing tweaks)
that is written back byte-for-byte, and *blocks* that are selected, reordered or
regenerated. `tests/test_render.py::test_identity_round_trip` proves that rendering the
base's own content reproduces the base.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from .latex import find_calls, read_group, to_text
from .models import BaseEntry, BaseResume, ListFile

SRC_FILES = ("heading", "education", "experience", "projects", "certificates", "skills")
FIXED_FILES = ("resume.tex", "custom-commands.tex", "src/heading.tex")


class BaseError(ValueError):
    pass


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except FileNotFoundError as e:
        raise BaseError(f"missing base file: {path}") from e


_BLOCK_RE = re.compile(r"[^\n]*\S[^\n]*(?:\n[^\n]*\S[^\n]*)*")


def parse_list_file(text: str, name: str) -> ListFile:
    start_tok, end_tok = r"\resumeSubHeadingListStart", r"\resumeSubHeadingListEnd"
    if start_tok not in text or end_tok not in text:
        raise BaseError(f"{name}: expected {start_tok} … {end_tok}")
    i = text.index(start_tok) + len(start_tok)
    j = text.rindex(end_tok)
    region = text[i:j]
    matches = list(_BLOCK_RE.finditer(region))
    if not matches:
        raise BaseError(f"{name}: list is empty")
    # The last "block" may be only the indentation before ListEnd; whitespace-only runs
    # never match _BLOCK_RE, so every match is real content.
    return ListFile(
        prefix=text[:i],
        head=region[: matches[0].start()],
        tail=region[matches[-1].end() :],
        suffix=text[j:],
        blocks=[m.group(0) for m in matches],
    )


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _parse_items(block: str) -> tuple[list[str], str]:
    calls = find_calls(block, "resumeItem", 1)
    items = [c.args[0] for c in calls]
    item_indent = "        "
    for line in block.splitlines():
        if line.lstrip().startswith(r"\resumeItem{"):
            item_indent = _indent(line)
            break
    return items, item_indent


def parse_experience_block(block: str) -> BaseEntry:
    calls = find_calls(block, "resumeSubheading", 4)
    if len(calls) != 1:
        raise BaseError("experience block must contain exactly one \\resumeSubheading")
    lines = block.split("\n")
    try:
        start = next(k for k, ln in enumerate(lines) if r"\resumeItemListStart" in ln)
        end = next(k for k, ln in enumerate(lines) if r"\resumeItemListEnd" in ln)
    except StopIteration as e:
        raise BaseError("experience block needs \\resumeItemListStart/End") from e
    bullets, item_indent = _parse_items(block)
    return BaseEntry(
        block=block,
        header="\n".join(lines[: start + 1]),
        footer=lines[end],
        title_tex=calls[0].args[0],
        stack=[],
        link=None,
        link_tex="",
        bullets_tex=bullets,
        indent=_indent(lines[0]),
        item_indent=item_indent,
    )


def parse_project_block(block: str) -> BaseEntry:
    calls = find_calls(block, "resumeProjectHeading", 2)
    if len(calls) != 1:
        raise BaseError("project block must contain exactly one \\resumeProjectHeading")
    left, right = calls[0].args
    m = re.search(r"\\textbf(?![A-Za-z])", left)
    if not m:
        raise BaseError("project heading needs \\textbf{title}")
    title, _ = read_group(left, m.end())
    stack: list[str] = []
    m = re.search(r"\\emph(?![A-Za-z])", left)
    if m:
        stack_tex, _ = read_group(left, m.end())
        stack = [to_text(s) for s in stack_tex.split(",") if s.strip()]
    link = None
    m = re.search(r"\\href(?![A-Za-z])", right)
    if m:
        link, _ = read_group(right, m.end())
    bullets, item_indent = _parse_items(block)
    return BaseEntry(
        block=block, header="", footer="", title_tex=title, stack=stack, link=link,
        link_tex=right, bullets_tex=bullets, indent=_indent(block.split("\n")[0]),
        item_indent=item_indent,
    )


def parse_base(directory: Path, lang: Literal["en", "tr"]) -> BaseResume:
    for f in FIXED_FILES:
        if not (directory / f).exists():
            raise BaseError(f"missing base file: {directory / f}")

    edu = _read(directory / "src/education.tex")
    label_tex, courses = "", []
    for call in find_calls(edu, "resumeItem", 1):
        m = re.match(r"^\s*(\\textbf\{[^{}]*:\})\s*(.*)$", call.args[0], re.S)
        if m:
            label_tex = m.group(1)
            courses = [to_text(c) for c in m.group(2).split(",") if c.strip()]
    if not label_tex:
        raise BaseError(f"{lang}/src/education.tex: expected "
                        "\\resumeItem{\\textbf{Label:} course, course, ...}")

    exp = parse_list_file(_read(directory / "src/experience.tex"), "experience.tex")
    proj = parse_list_file(_read(directory / "src/projects.tex"), "projects.tex")
    cert = parse_list_file(_read(directory / "src/certificates.tex"), "certificates.tex")
    cert_names = []
    for b in cert.blocks:
        m = re.search(r"\\textbf(?![A-Za-z])", b)
        if not m:
            raise BaseError("certificate block needs \\textbf{name}")
        cert_names.append(to_text(read_group(b, m.end())[0]))

    skills = _read(directory / "src/skills.tex")
    lines = skills.split("\n")
    rows: list[tuple[str, str, str]] = []
    first = last = None
    for k, line in enumerate(lines):
        s = line.strip()
        if s.startswith(r"\textbf{"):
            group, i = read_group(s, len(r"\textbf"))
            items, _ = read_group(s, i)
            if not items.startswith(":"):
                raise BaseError(f"skills row must be \\textbf{{Group}}{{: items}} \\\\ : {s!r}")
            rows.append((_indent(line), group, items[1:].strip()))
            first = k if first is None else first
            last = k
    if first is None or last is None:
        raise BaseError(f"{lang}/src/skills.tex: no \\textbf{{Group}}{{: items}} rows found")

    return BaseResume(
        lang=lang,
        dir=str(directory),
        education_file=edu,
        courses_label_tex=label_tex,
        courses=courses,
        experience=exp,
        experience_entries=[parse_experience_block(b) for b in exp.blocks],
        projects=proj,
        project_entries=[parse_project_block(b) for b in proj.blocks],
        certificates=cert,
        certificate_names=cert_names,
        skills_prefix="\n".join(lines[:first]) + "\n",
        skills_suffix="\n" + "\n".join(lines[last + 1 :]),
        skill_rows=rows,
    )
