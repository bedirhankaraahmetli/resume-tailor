"""The fact guard: nothing reaches the page that the inventory cannot back.

Checks are deterministic and run on every LLM result before rendering. Each violation is
a sentence the repair prompt can act on, so the second attempt knows exactly what to fix.

What the guard can and cannot prove: numbers, ids, statuses, skills, stack items, known
technology names and listed forbidden phrases are checked mechanically. Prose-level
"do not claim" notes ("do not say you built the frontend") are given to the model
verbatim and listed in the report for a human eye; no regex can verify paraphrase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import Catalog
from .models import Bullet, CoverLetter, Tailoring
from .text import contains_term, extract_numbers, fold

# Technologies an LLM is likely to borrow from a posting. If one appears in a bullet but
# nowhere in the inventory, it was invented. Extend freely; false positives are cheap
# (one repair round), false negatives put an untrue claim on a resume.
TECH_TERMS = [
    "AWS", "Azure", "GCP", "Google Cloud", "Kubernetes", "K8s", "Terraform", "Ansible",
    "Jenkins", "GitHub Actions", "GitLab CI", "CircleCI", "SwiftUI", "UIKit",
    "Core Data", "SwiftData", "Objective-C", "React Native", "Jetpack Compose", "Vue",
    "Svelte", "Next.js", "Node.js", "Express.js", "NestJS", "Django", "FastAPI", "Spring Cloud",
    "Kafka", "RabbitMQ", "Redis", "MongoDB", "Cassandra", "Elasticsearch", "DynamoDB",
    "Snowflake", "BigQuery", "Databricks", "Spark", "PySpark", "Hadoop", "Airflow", "dbt",
    "Tableau", "Power BI", "Looker", "Keras", "JAX", "Hugging Face", "Transformers",
    "LangChain", "LlamaIndex", "OpenCV", "YOLO", "BERT", "RAG", "MLflow", "Kubeflow",
    "SageMaker", "Vertex AI", "TypeScript", "JavaScript", "Golang", "Rust", "C++",
    "Scala", "Ruby", "PHP", ".NET", "ASP.NET", "GraphQL", "Firebase", "Supabase",
    "Kotlin Multiplatform", "Unreal", "Godot", "MATLAB",
    "SAP", "Salesforce", "Linux", "Bash", "CI/CD", "Prometheus", "Grafana", "Datadog",
]


@dataclass(frozen=True)
class Violation:
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.where}: {self.message}"


@dataclass
class GuardResult:
    violations: list[Violation]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations


_PASSIVE_TR = re.compile(r"\b\w+(ıldı|ildi|uldu|üldü|ndı|ndi|ndu|ndü|ınmıştır|ilmiştir)[.!]?$")


class _Texts:
    """The checks every piece of generated prose gets: numbers against the cited sources,
    the never-claim list and invented technologies. Shared by resumes and cover letters."""

    def __init__(self, cat: Catalog, v: list[Violation]) -> None:
        self.cat, self.v = cat, v
        self.inv_folded = fold(cat.inventory.raw)
        self.never_terms = [*cat.inventory.never_claim, *cat.config.resume.never_claim_tr]
        self.versioned = sorted(
            {s for e in cat.entries.values() for s in e.allowed_stack if re.search(r"\d", s)}
            | {s for s in cat.skills if re.search(r"\d", s)},
            key=len, reverse=True,
        )

    def known_source(self, sid: str) -> bool:
        return sid in self.cat.entries or sid in self.cat.general_sources

    def source_text(self, ids: list[str]) -> str:
        parts = []
        for sid in ids:
            if sid in self.cat.entries:
                parts.append(self.cat.entries[sid].source_text)
            elif sid in self.cat.general_sources:
                parts.append(self.cat.general_sources[sid])
        return "\n".join(parts)

    def forbidden(self, ids: list[str]) -> set[str]:
        out: set[str] = set()
        for sid in ids:
            if sid in self.cat.entries:
                out |= self.cat.entries[sid].forbidden_numbers
        return out

    def check_text(self, where: str, text: str, allowed_numbers: set[str],
                   forbidden: set[str]) -> None:
        v = self.v
        # "Java 21" and "JUnit 5" are names, not quantities: drop known versioned names
        # before counting numbers, so they need not be (and cannot be) cited as counts.
        counted = text
        for term in self.versioned:
            counted = re.sub(r"(?<!\w)" + re.escape(term) + r"(?!\w)", " ", counted,
                             flags=re.IGNORECASE)
        numbers = extract_numbers(counted)
        for n in sorted(numbers - allowed_numbers):
            v.append(Violation("number", where, f"'{n}' does not appear in the cited sources"))
        for n in sorted(numbers & forbidden):
            v.append(Violation("forbidden-number", where,
                               f"'{n}' is explicitly ruled out by the inventory"))
        ft = fold(text)
        for term in self.never_terms:
            if contains_term(ft, term):
                v.append(Violation("never-claim", where, f"mentions '{term}', which the "
                                   "inventory says never to claim"))
        for term in TECH_TERMS:
            if contains_term(ft, term) and not contains_term(self.inv_folded, term):
                v.append(Violation("unknown-tech", where,
                                   f"mentions '{term}', which is not in the inventory"))


def check(cat: Catalog, t: Tailoring) -> GuardResult:
    v: list[Violation] = []
    warn: list[str] = []
    cfg = cat.config.resume
    texts = _Texts(cat, v)
    known_source, source_text, check_text = texts.known_source, texts.source_text, texts.check_text

    def check_bullet(where: str, parent: str, b: Bullet) -> None:
        if not b.sources:
            v.append(Violation("sources", where, "bullet cites no source"))
        for sid in b.sources:
            if not known_source(sid):
                v.append(Violation("sources", where, f"unknown source id '{sid}'"))
        ids = [*b.sources, parent]
        allowed = extract_numbers(source_text(ids))
        forbidden = texts.forbidden(ids)
        if not b.en.strip() or not b.tr.strip():
            v.append(Violation("empty", where, "bullet needs both 'en' and 'tr' text"))
        check_text(where + " (en)", b.en, allowed, forbidden)
        check_text(where + " (tr)", b.tr, allowed, forbidden)
        if _PASSIVE_TR.search(b.tr.strip()):
            warn.append(f"{where} (tr): may be passive voice; use first person "
                        "('geliştirdim', not 'geliştirildi')")

    # --- experience: every entry, in inventory order is not required, but all present
    seen = [e.id for e in t.experience]
    for eid in cat.experience_ids:
        if eid not in seen:
            v.append(Violation("experience", eid, "experience must never be dropped"))
    for sel in t.experience:
        if sel.id not in cat.experience_ids:
            v.append(Violation("unknown-id", sel.id, "not an experience id"))
            continue
        if not sel.bullets:
            v.append(Violation("bullets", sel.id, "needs at least one bullet"))
        for i, b in enumerate(sel.bullets, 1):
            check_bullet(f"{sel.id} bullet {i}", sel.id, b)
    if len(set(seen)) != len(seen):
        v.append(Violation("duplicate", "experience", "an experience is listed twice"))

    # --- projects
    pids = [p.id for p in t.projects]
    if len(set(pids)) != len(pids):
        v.append(Violation("duplicate", "projects", "a project is listed twice"))
    need = min(cfg.min_projects, len(cat.usable_project_ids()))
    if len(pids) < need:
        v.append(Violation("projects", "projects", f"include at least {need} projects"))
    for ps in t.projects:
        entry = cat.entries.get(ps.id)
        if entry is None or entry.kind != "project":
            v.append(Violation("unknown-id", ps.id, "not a project id"))
            continue
        if not entry.inv.usable:
            v.append(Violation("status", ps.id, f"status '{entry.inv.status}' may not be used"
                               + (" (in-progress needs 'Resume use: allowed')"
                                  if entry.inv.status == "in-progress" else "")))
        if not ps.bullets:
            v.append(Violation("bullets", ps.id, "needs at least one bullet"))
        if not ps.stack:
            v.append(Violation("stack", ps.id, "needs at least one stack item"))
        if len(ps.stack) > cfg.max_stack_items:
            v.append(Violation("stack", ps.id, f"at most {cfg.max_stack_items} stack items"))
        allowed_stack = {fold(s) for s in entry.allowed_stack}
        for s in ps.stack:
            if fold(s) not in allowed_stack:
                v.append(Violation("stack", ps.id, f"'{s}' is not in this project's stack"))
        if not entry.on_base:
            for lang, title in (("en", ps.title_en), ("tr", ps.title_tr)):
                if not title:
                    v.append(Violation("title", ps.id, f"needs title_{lang} (not on the base)"))
                else:
                    check_text(f"{ps.id} title_{lang}", title,
                               extract_numbers(entry.source_text), entry.forbidden_numbers)
        for i, b in enumerate(ps.bullets, 1):
            check_bullet(f"{ps.id} bullet {i}", ps.id, b)

    # --- reserve
    present = set(seen) | set(pids)
    for i, r in enumerate(t.reserve, 1):
        if r.parent not in present:
            v.append(Violation("reserve", f"reserve {i}", f"parent '{r.parent}' is not selected"))
        else:
            check_bullet(f"reserve {i} ({r.parent})", r.parent, r.bullet)

    # --- education
    if len(t.education) != 1:
        v.append(Violation("education", "education", "exactly one education entry"))
    for e in t.education:
        if len(e.courses) < cfg.min_courses:
            v.append(Violation("education", "courses", f"list at least {cfg.min_courses} courses"))
        for c in e.courses:
            if cat.course(c) is None:
                v.append(Violation("course", c, "not in the inventory course list"))

    # --- certificates
    for cid in t.certificates:
        if cid not in cat.certificates:
            v.append(Violation("unknown-id", cid, "not a certificate id"))
    if len(set(t.certificates)) != len(t.certificates):
        v.append(Violation("duplicate", "certificates", "a certificate is listed twice"))

    # --- skills
    canon = {fold(s) for s in cat.skills}
    for g in t.skills:
        if g.group not in cat.skill_groups:
            v.append(Violation("skill-group", g.group, "not a skill group id"))
        if not g.items:
            v.append(Violation("skill-group", g.group, "empty group"))
        for s in g.items:
            if fold(s) not in canon:
                v.append(Violation("skill", g.group, f"'{s}' has no evidence in the inventory"))
    groups = [g.group for g in t.skills]
    if len(set(groups)) != len(groups):
        v.append(Violation("duplicate", "skills", "a skill group is listed twice"))

    return GuardResult(v, warn)


# Plain words only: the letter's links and contact details come from the base heading.
_CONTACT = re.compile(r"https?://|www\.|\S+@\S+\.\w+")
LETTER_MAX_WORDS = 400


def check_letter(cat: Catalog, letter: CoverLetter, langs: tuple[str, ...]) -> GuardResult:
    """The fact guard for a cover letter: every paragraph cites its sources, and its
    numbers, terms and technologies pass the same checks as a resume bullet."""
    v: list[Violation] = []
    texts = _Texts(cat, v)
    if not 2 <= len(letter.paragraphs) <= 5:
        v.append(Violation("letter", "paragraphs", "write 3 or 4 body paragraphs"))
    words = dict.fromkeys(langs, 0)
    for i, p in enumerate(letter.paragraphs, 1):
        where = f"letter paragraph {i}"
        for sid in p.sources:
            if not texts.known_source(sid):
                v.append(Violation("sources", where, f"unknown source id '{sid}'"))
            elif sid in cat.entries and not cat.entries[sid].inv.usable:
                v.append(Violation("status", where, f"'{sid}' may not be used "
                                   f"(status '{cat.entries[sid].inv.status}')"))
        allowed = extract_numbers(texts.source_text(p.sources))
        forbidden = texts.forbidden(p.sources)
        for lang in langs:
            text = p.en if lang == "en" else p.tr
            if not text or not text.strip():
                v.append(Violation("empty", where, f"needs '{lang}' text"))
                continue
            words[lang] += len(text.split())
            texts.check_text(f"{where} ({lang})", text, allowed, forbidden)
            if _CONTACT.search(text):
                v.append(Violation("contact", f"{where} ({lang})", "no links, emails or "
                                   "contact details; the letterhead has them"))
    for lang, n in words.items():
        if n > LETTER_MAX_WORDS:
            v.append(Violation("length", f"letter ({lang})", f"{n} words; keep it under "
                               f"{LETTER_MAX_WORDS} so it fits one page"))
    return GuardResult(v, [])
