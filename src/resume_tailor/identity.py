"""The base resume's own content expressed as a `Tailoring`.

Rendering this must reproduce the base files (whitespace aside). That is the proof that
the renderer cannot change the layout, and `tailor check` runs it on the real data.
"""

from __future__ import annotations

import re

from .catalog import Catalog, _slug_id
from .latex import to_text
from .models import (
    Bullet,
    EducationSel,
    ExperienceSel,
    ProjectSel,
    SkillGroupSel,
    Tailoring,
)


def identity_tailoring(cat: Catalog) -> Tailoring:
    def bullets(entry_id: str) -> list[Bullet]:
        e = cat.entries[entry_id]
        assert e.base_en is not None and e.base_tr is not None
        return [
            Bullet(sources=[entry_id], priority=1, en=to_text(en), tr=to_text(tr))
            for en, tr in zip(e.base_en.bullets_tex, e.base_tr.bullets_tex, strict=True)
        ]

    projects = []
    for b in cat.base_en.project_entries:
        pid = next(p for p in cat.project_ids
                   if (cat.entries[p].base_en is not None and cat.entries[p].base_en is b))
        projects.append(ProjectSel(id=pid, title_en=None, title_tr=None,
                                   stack=b.stack, bullets=bullets(pid)))

    fixed = cat.config.resume.fixed_skill_rows
    groups = []
    for _, g, items in cat.base_en.skill_rows[fixed:]:
        gid = _slug_id(g)
        groups.append(SkillGroupSel(group=gid, items=[to_text(i) for i in items.split(",")]))

    cert_ids = sorted(cat.certificates, key=lambda c: cat.certificates[c].en_block)
    return Tailoring(
        experience=[ExperienceSel(id=e, bullets=bullets(e)) for e in cat.experience_ids],
        projects=projects,
        education=[EducationSel(id="2.1", courses=cat.base_en.courses)],
        certificates=cert_ids,
        skills=groups,
        reserve=[],
        changes=[],
        gaps=[],
    )


def normalize_tex(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\r\n", "\n")).strip()
