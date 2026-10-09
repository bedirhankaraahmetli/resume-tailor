"""The catalog: inventory + both base resumes + config, joined by id.

Base entries are matched to inventory entries by something both sides already carry
(experience: employer name and order; projects: link URL; certificates: official name),
so the owner never has to maintain ids in the .tex files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .base import parse_base
from .config import Config
from .inventory import parse_inventory, split_terms
from .latex import escape, to_text
from .models import BaseEntry, BaseResume, InvCertificate, Inventory, InvEntry
from .text import extract_numbers, fold


class CatalogError(ValueError):
    pass


@dataclass
class CatEntry:
    id: str
    kind: str
    inv: InvEntry
    base_en: BaseEntry | None
    base_tr: BaseEntry | None
    allowed_stack: list[str]
    source_text: str
    forbidden_numbers: set[str]

    @property
    def on_base(self) -> bool:
        return self.base_en is not None


@dataclass
class CatCourse:
    en: str
    tr: str


@dataclass
class CatCert:
    id: str
    inv: InvCertificate
    en_block: int
    tr_block: int


@dataclass
class CatGroup:
    id: str
    en_tex: str
    tr_tex: str


@dataclass
class Catalog:
    config: Config
    inventory: Inventory
    base_en: BaseResume
    base_tr: BaseResume
    entries: dict[str, CatEntry]
    experience_ids: list[str]
    project_ids: list[str]
    courses: list[CatCourse]
    certificates: dict[str, CatCert]
    skill_groups: dict[str, CatGroup]
    skills: list[str]
    general_sources: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def base(self, lang: str) -> BaseResume:
        return self.base_en if lang == "en" else self.base_tr

    def course(self, name: str) -> CatCourse | None:
        for c in self.courses:
            if fold(c.en) == fold(name):
                return c
        return None

    def evidence_text(self) -> str:
        """Everything the owner may claim: positive inventory text, skills, courses,
        certificates. Never the "do not claim" or "never claim" lines, which name exactly
        the things the owner does NOT have."""
        parts = [e.source_text for e in self.entries.values() if e.inv.usable]
        parts += self.skills + [c.en for c in self.courses]
        parts += [f"{c.inv.name} {c.inv.issuer}" for c in self.certificates.values()]
        return "\n".join(parts)

    def usable_project_ids(self) -> list[str]:
        return [p for p in self.project_ids if self.entries[p].inv.usable]


def _norm_url(u: str | None) -> str:
    return (u or "").strip().rstrip("/").lower()


def _slug_id(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(to_text(text))).strip("-")


def build_catalog(data_dir: Path, config: Config) -> Catalog:
    inv = parse_inventory((data_dir / "career-inventory.md").read_text(encoding="utf-8"))
    base_en = parse_base(data_dir / "base" / "en", "en")
    base_tr = parse_base(data_dir / "base" / "tr", "tr")
    warnings: list[str] = []
    entries: dict[str, CatEntry] = {}

    def make(e: InvEntry, ben: BaseEntry | None, btr: BaseEntry | None) -> CatEntry:
        base_text: list[str] = []
        stack = list(e.stack)
        for b in (ben, btr):
            if b is not None:
                base_text.extend(to_text(x) for x in b.bullets_tex)
        if ben is not None:
            for s in ben.stack:
                for t in split_terms(s):
                    if t not in stack:
                        stack.append(t)
        source = "\n".join([e.positive_text, *base_text])
        forbidden = extract_numbers(e.negative_text) - extract_numbers(source)
        return CatEntry(e.id, e.kind, e, ben, btr, stack, source, forbidden)

    # Experience: same order in inventory and both bases, employer name must agree.
    if not (len(inv.experience) == len(base_en.experience_entries)
            == len(base_tr.experience_entries)):
        raise CatalogError(
            f"experience count differs: inventory {len(inv.experience)}, base/en "
            f"{len(base_en.experience_entries)}, base/tr {len(base_tr.experience_entries)}. "
            "Every experience must appear in both base resumes, in the same order."
        )
    for e, ben, btr in zip(inv.experience, base_en.experience_entries,
                           base_tr.experience_entries, strict=True):
        org = fold(to_text(ben.title_tex))
        if org not in fold(e.title):
            raise CatalogError(
                f"experience order mismatch: inventory '{e.title}' vs base "
                f"'{to_text(ben.title_tex)}'"
            )
        if len(ben.bullets_tex) != len(btr.bullets_tex):
            warnings.append(f"{e.id}: base/en and base/tr have different bullet counts")
        entries[e.id] = make(e, ben, btr)

    # Projects: matched by link.
    by_link_en = {_norm_url(b.link): b for b in base_en.project_entries}
    by_link_tr = {_norm_url(b.link): b for b in base_tr.project_entries}
    inv_links = {_norm_url(p.link) for p in inv.projects}
    for link in by_link_en:
        if link not in inv_links:
            raise CatalogError(f"base/en project with link {link!r} has no inventory entry")
    for p in inv.projects:
        key = _norm_url(p.link)
        pen = by_link_en.get(key) if key else None
        ptr = by_link_tr.get(key) if key else None
        if (pen is None) != (ptr is None):
            raise CatalogError(f"{p.id}: on one base resume but not the other")
        entries[p.id] = make(p, pen, ptr)

    # Courses: English names from the inventory; Turkish from base/tr (same order as
    # base/en) or from config.resume.course_names_tr.
    tr_by_en = {fold(en): tr for en, tr in zip(base_en.courses, base_tr.courses, strict=False)}
    tr_by_en.update({fold(k): v for k, v in config.resume.course_names_tr.items()})
    courses = []
    for c in inv.courses:
        tr = tr_by_en.get(fold(c))
        if tr is None:
            warnings.append(f"course '{c}' has no Turkish name (config resume.course_names_tr)")
            tr = c
        courses.append(CatCourse(c, tr))

    certs: dict[str, CatCert] = {}
    en_names = [fold(n) for n in base_en.certificate_names]
    tr_names = [fold(n) for n in base_tr.certificate_names]
    for cert in inv.certificates:
        n = fold(cert.name)
        if n not in en_names or n not in tr_names:
            warnings.append(f"certificate '{cert.name}' is not on both base resumes")
            continue
        certs[cert.id] = CatCert(cert.id, cert, en_names.index(n), tr_names.index(n))

    fixed = config.resume.fixed_skill_rows
    rows_en, rows_tr = base_en.skill_rows[fixed:], base_tr.skill_rows[fixed:]
    if len(rows_en) != len(rows_tr):
        raise CatalogError("base/en and base/tr must have the same skill groups in the same order")
    groups: dict[str, CatGroup] = {}
    for (_, gen, _), (_, gtr, _) in zip(rows_en, rows_tr, strict=True):
        gid = _slug_id(gen)
        groups[gid] = CatGroup(gid, gen, gtr)
    for g in config.resume.extra_skill_groups:
        groups.setdefault(g.id, CatGroup(g.id, escape(g.en), escape(g.tr)))

    skills = list(inv.skills)
    for _, _, items in rows_en:
        for t in split_terms(to_text(items)):
            if t not in skills:
                skills.append(t)

    general = {
        "2": inv.education_text,
        "5": "\n".join(f"{c.name} {c.issuer} {c.date_en}" for c in inv.certificates),
        "6": inv.skills_text,
    }

    return Catalog(
        config=config, inventory=inv, base_en=base_en, base_tr=base_tr, entries=entries,
        experience_ids=[e.id for e in inv.experience],
        project_ids=[p.id for p in inv.projects], courses=courses, certificates=certs,
        skill_groups=groups, skills=skills, general_sources=general, warnings=warnings,
    )
