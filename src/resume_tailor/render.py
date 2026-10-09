"""Render validated `Tailoring` JSON into `src/*.tex` for one language.

Only the item regions are regenerated. Frames (section titles, list macros, spacing) are
the base's own bytes, and facts the LLM must not touch (employer, dates, education,
certificate names, links) are copied from the base or the inventory by id.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .catalog import Catalog, CatEntry
from .latex import escape, find_calls
from .models import ListFile, Tailoring


class RenderError(ValueError):
    pass


def _assemble(lf: ListFile, blocks: list[str]) -> str:
    return lf.prefix + lf.head + "\n\n".join(blocks) + lf.tail + lf.suffix


def _href(url: str, label: str) -> str:
    safe = url.replace("%", r"\%").replace("#", r"\#")
    return rf"\small\href{{{safe}}}{{\underline{{{escape(label)}}}}}"


def _link_label(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return "GitHub" if host == "github.com" else host


def _items(indent: str, texts: list[str]) -> list[str]:
    return [f"{indent}\\resumeItem{{{escape(t)}}}" for t in texts]


def render_education(cat: Catalog, t: Tailoring, lang: str) -> str:
    base = cat.base(lang)
    if len(t.education) != 1:
        raise RenderError("exactly one education entry is supported")
    names = []
    for name in t.education[0].courses:
        c = cat.course(name)
        if c is None:
            raise RenderError(f"unknown course {name!r}")
        names.append(c.en if lang == "en" else c.tr)
    for call in find_calls(base.education_file, "resumeItem", 1):
        if call.args[0].lstrip().startswith(base.courses_label_tex):
            new = rf"\resumeItem{{{base.courses_label_tex} {', '.join(escape(n) for n in names)}}}"
            return base.education_file[: call.start] + new + base.education_file[call.end :]
    raise RenderError("course line not found in base education.tex")


def render_experience(cat: Catalog, t: Tailoring, lang: str) -> str:
    base = cat.base(lang)
    blocks = []
    for sel in t.experience:
        entry = cat.entries[sel.id]
        b = entry.base_en if lang == "en" else entry.base_tr
        if b is None:
            raise RenderError(f"{sel.id} is not on base/{lang}")
        texts = [x.en if lang == "en" else x.tr for x in sel.bullets]
        blocks.append("\n".join([b.header, *_items(b.item_indent, texts), b.footer]))
    return _assemble(base.experience, blocks)


def _project_title(cat: Catalog, entry: CatEntry, lang: str, title_en: str | None,
                   title_tr: str | None) -> str:
    b = entry.base_en if lang == "en" else entry.base_tr
    if b is not None:
        title = b.title_tex
    else:
        plain = title_en if lang == "en" else title_tr
        if not plain:
            raise RenderError(f"{entry.id} is not on the base resume and has no title_{lang}")
        title = escape(plain)
    if entry.inv.status == "in-progress":
        title += " (" + escape(cat.config.resume.in_progress_label[lang]) + ")"
    return title


def render_projects(cat: Catalog, t: Tailoring, lang: str) -> str:
    base = cat.base(lang)
    ref = base.project_entries[0]
    ind, item_ind = ref.indent, ref.item_indent
    blocks = []
    for sel in t.projects:
        entry = cat.entries[sel.id]
        b = entry.base_en if lang == "en" else entry.base_tr
        title = _project_title(cat, entry, lang, sel.title_en, sel.title_tr)
        stack = ", ".join(escape(s) for s in sel.stack)
        if b is not None:
            link = b.link_tex
        elif entry.inv.link:
            link = _href(entry.inv.link, _link_label(entry.inv.link))
        else:
            link = ""
        texts = [x.en if lang == "en" else x.tr for x in sel.bullets]
        blocks.append("\n".join([
            f"{ind}\\resumeProjectHeading",
            f"{ind}{{\\textbf{{{title}}} $|$ \\emph{{{stack}}}}}{{{link}}}",
            f"{ind}\\resumeItemListStart",
            *_items(item_ind, texts),
            f"{ind}\\resumeItemListEnd",
        ]))
    return _assemble(base.projects, blocks)


def render_certificates(cat: Catalog, t: Tailoring, lang: str) -> str:
    base = cat.base(lang)
    blocks = []
    for cid in t.certificates:
        c = cat.certificates[cid]
        blocks.append(base.certificates.blocks[c.en_block if lang == "en" else c.tr_block])
    return _assemble(base.certificates, blocks)


def render_skills(cat: Catalog, t: Tailoring, lang: str) -> str:
    base = cat.base(lang)
    fixed = cat.config.resume.fixed_skill_rows
    rows = [f"{i}\\textbf{{{g}}}{{: {items}}} \\\\" for i, g, items in base.skill_rows[:fixed]]
    indent = base.skill_rows[fixed][0] if len(base.skill_rows) > fixed else "        "
    tr_names = cat.config.resume.skill_names_tr
    for sel in t.skills:
        g = cat.skill_groups[sel.group]
        names = [tr_names.get(s, s) if lang == "tr" else s for s in sel.items]
        group = g.en_tex if lang == "en" else g.tr_tex
        rows.append(f"{indent}\\textbf{{{group}}}{{: {', '.join(escape(n) for n in names)}}} \\\\")
    return base.skills_prefix + "\n".join(rows) + base.skills_suffix


def render_all(cat: Catalog, t: Tailoring, lang: str) -> dict[str, str]:
    """Relative path → content for every tailored src file."""
    return {
        "src/education.tex": render_education(cat, t, lang),
        "src/experience.tex": render_experience(cat, t, lang),
        "src/projects.tex": render_projects(cat, t, lang),
        "src/certificates.tex": render_certificates(cat, t, lang),
        "src/skills.tex": render_skills(cat, t, lang),
    }
