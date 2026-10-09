"""Build the text each LLM call sees.

Prompt-cache layout: the static block (rules + catalog + redacted inventory + base
resume digest) is byte-identical on every run with unchanged data, so it goes first and
is the cached prefix. Everything per-run (analysis, posting, note) goes in the user turn.
Nothing here may contain a timestamp, a run id or unsorted data.
"""

from __future__ import annotations

import json
from pathlib import Path

from .catalog import Catalog
from .config import Config, Preset
from .inventory import strip_contact_section
from .latex import to_text
from .models import Analysis, CoverLetter, Tailoring
from .providers.base import LLMCall
from .redaction import assert_clean, redact

PROMPT_VERSION = "v1"


def _prompts_dir() -> Path:
    packaged = Path(__file__).parent / "_prompts"
    return packaged if packaged.exists() else Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(name: str) -> str:
    return (_prompts_dir() / f"{name}.{PROMPT_VERSION}.md").read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    # str.format would choke on the braces inside JSON values.
    for k, v in values.items():
        template = template.replace("{" + k + "}", v)
    return template


def catalog_json(cat: Catalog) -> str:
    cfg = cat.config.resume
    data = {
        "limits": {"min_projects": cfg.min_projects, "max_stack_items": cfg.max_stack_items,
                   "min_courses": cfg.min_courses},
        "experience": [{"id": e, "title": cat.entries[e].inv.title} for e in cat.experience_ids],
        "projects": [
            {
                "id": p,
                "title": cat.entries[p].inv.title,
                "status": cat.entries[p].inv.status,
                "usable": cat.entries[p].inv.usable,
                "on_base_resume": cat.entries[p].on_base,
                "allowed_stack": cat.entries[p].allowed_stack,
            }
            for p in cat.project_ids
        ],
        "education": [{"id": "2.1", "note": "one entry; only the course list is tailored"}],
        "courses": [c.en for c in cat.courses],
        "certificates": [{"id": c.id, "name": c.inv.name, "issuer": c.inv.issuer}
                         for c in cat.certificates.values()],
        "skill_groups": [{"id": g.id, "en": to_text(g.en_tex), "tr": to_text(g.tr_tex)}
                         for g in cat.skill_groups.values()],
        "skills": cat.skills,
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


def base_digest(cat: Catalog) -> str:
    lines = []
    for eid in [*cat.experience_ids, *cat.project_ids]:
        e = cat.entries[eid]
        if e.base_en is None or e.base_tr is None:
            continue
        lines.append(f"## {eid}: {to_text(e.base_en.title_tex)} / {to_text(e.base_tr.title_tex)}")
        if e.base_en.stack:
            lines.append("Stack on base: " + ", ".join(e.base_en.stack))
        lines += [f"EN: {to_text(b)}" for b in e.base_en.bullets_tex]
        lines += [f"TR: {to_text(b)}" for b in e.base_tr.bullets_tex]
        lines.append("")
    lines.append("## Courses on base (EN / TR)")
    lines.append(", ".join(cat.base_en.courses))
    lines.append(", ".join(cat.base_tr.courses))
    fixed = cat.config.resume.fixed_skill_rows
    lines.append(f"\n## Skills on base (the first {fixed} row(s) are fixed and always kept)")
    for (_, g, items), (_, gt, _) in zip(cat.base_en.skill_rows, cat.base_tr.skill_rows,
                                         strict=False):
        lines.append(f"{to_text(g)} / {to_text(gt)}: {to_text(items)}")
    return "\n".join(lines)


def static_block(cat: Catalog) -> str:
    names, contacts = cat.config.owner.names, cat.config.owner.contact_strings
    inventory = redact(strip_contact_section(cat.inventory.raw), names, contacts)
    return "\n\n".join([
        load_prompt("rules"),
        "# CATALOG (ids and allowed values)\n\n```json\n" + catalog_json(cat) + "\n```",
        "# CAREER INVENTORY\n\n" + inventory,
        "# BASE RESUME (current wording, EN and TR)\n\n"
        + redact(base_digest(cat), names, contacts),
    ])


def letter_static_block(cat: Catalog) -> str:
    """Same facts as the tailoring block, under the letter's own rules. Its own cache
    prefix: the output schema differs, so it could not share the tailoring call's."""
    names, contacts = cat.config.owner.names, cat.config.owner.contact_strings
    inventory = redact(strip_contact_section(cat.inventory.raw), names, contacts)
    return "\n\n".join([
        load_prompt("letter"),
        "# CATALOG (ids and allowed values)\n\n```json\n" + catalog_json(cat) + "\n```",
        "# CAREER INVENTORY\n\n" + inventory,
        "# BASE RESUME (current wording, EN and TR)\n\n"
        + redact(base_digest(cat), names, contacts),
    ])


_LANG_LINE = {
    ("en",): "English only. Set every `tr` to null.",
    ("tr",): "Turkish only. Set every `en` to null.",
    ("en", "tr"): "English and Turkish: fill both `en` and `tr` in every paragraph.",
}


def letter_call(cat: Catalog, *, analysis: Analysis, posting: str, tailoring: Tailoring,
                note: str | None, langs: tuple[str, ...],
                model: str | None = None) -> LLMCall:
    names, contacts = cat.config.owner.names, cat.config.owner.contact_strings
    selection = [f"- {e.id}: {cat.entries[e.id].inv.title}" for e in tailoring.experience
                 if e.id in cat.entries]
    selection += [f"- {p.id}: {cat.entries[p.id].inv.title}" for p in tailoring.projects
                  if p.id in cat.entries]
    user = _fill(load_prompt("letter_request"), languages=_LANG_LINE[langs],
                 analysis=analysis.model_dump_json(indent=1),
                 posting=redact(posting, names, contacts),
                 selection="\n".join(selection) or "(none)",
                 note=redact(note, names, contacts) if note else "(none)")
    return _checked(LLMCall("letter", "tailor", letter_static_block(cat),
                            redact(user, names, contacts), CoverLetter, model), cat.config)


def _checked(call: LLMCall, config: Config) -> LLMCall:
    assert_clean(json.dumps([call.system, call.user], ensure_ascii=False),
                 config.owner.names, config.owner.contact_strings)
    return call


def analyze_call(config: Config, posting: str, model: str | None = None) -> LLMCall:
    call = LLMCall("analyze", "analyze", load_prompt("analyze"),
                   redact(posting, config.owner.names, config.owner.contact_strings),
                   Analysis, model)
    return _checked(call, config)


def tailor_call(cat: Catalog, *, analysis: Analysis | None, posting: str | None,
                note: str | None, preset: Preset | None = None,
                model: str | None = None) -> LLMCall:
    names, contacts = cat.config.owner.names, cat.config.owner.contact_strings
    note_text = redact(note, names, contacts) if note else "(none)"
    if preset is not None:
        user = _fill(load_prompt("preset"), position=preset.position, focus=preset.focus,
                     note=note_text)
    else:
        assert analysis is not None and posting is not None
        user = _fill(load_prompt("tailor"),
                     analysis=analysis.model_dump_json(indent=1),
                     posting=redact(posting, names, contacts), note=note_text)
    return _checked(LLMCall("tailor", "tailor", static_block(cat), user, Tailoring, model),
                    cat.config)


def repair_prompt(original: str, previous: str, errors: list[str]) -> str:
    return _fill(load_prompt("repair"), original=original, previous=previous,
                 errors="\n".join(f"- {e}" for e in errors))
