"""Data models.

Pydantic models are the contract with the LLM (their JSON Schema is what providers are
asked to produce) and with the web app (request and result files). Dataclasses hold the
parsed inventory and base resume, which never leave the process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# =======================================================================================
# LLM output: posting analysis (call 1)
# =======================================================================================


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Keyword(_Strict):
    term: str = Field(description="Normalized keyword, e.g. 'machine learning'.")
    synonyms: list[str] = Field(
        description="Other spellings or abbreviations, in English and Turkish, e.g. ['ML', "
        "'makine öğrenmesi']."
    )
    importance: Literal["must", "nice"]


class Analysis(_Strict):
    company: str | None = Field(description="Hiring company name, or null if not stated.")
    position: str = Field(
        description="Job title exactly as written in the posting (keep an English title "
        "English even in a Turkish posting)."
    )
    posting_language: Literal["en", "tr", "other"]
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "unspecified"]
    must_have: list[str]
    nice_to_have: list[str]
    keywords: list[Keyword] = Field(description="15 to 30 ATS keywords.")


# =======================================================================================
# LLM output: tailoring (call 2)
# =======================================================================================


class Bullet(_Strict):
    sources: list[str] = Field(
        description="Inventory section ids the facts come from, e.g. ['4.1']."
    )
    priority: int = Field(ge=1, le=5, description="1 = keep longest, 5 = drop first.")
    en: str = Field(description="English bullet, plain text, no LaTeX.")
    tr: str = Field(
        description="Turkish bullet, plain text, active first-person past tense "
        "('geliştirdim'), never passive."
    )


class ExperienceSel(_Strict):
    id: str
    bullets: list[Bullet]


class ProjectSel(_Strict):
    id: str
    title_en: str | None = Field(
        description="Only for projects NOT on the base resume: short English title. "
        "Null for base projects."
    )
    title_tr: str | None = Field(
        description="Only for projects NOT on the base resume: Turkish title. Null for base "
        "projects."
    )
    stack: list[str] = Field(description="At most 7 items, from this project's allowed stack.")
    bullets: list[Bullet]


class EducationSel(_Strict):
    id: str
    courses: list[str] = Field(description="Course names from the catalog, most relevant first.")


class SkillGroupSel(_Strict):
    group: str = Field(description="A skill group id from the catalog.")
    items: list[str] = Field(description="Skills from the catalog, most relevant first.")


class ReserveBullet(_Strict):
    parent: str = Field(description="Experience or project id this bullet belongs to.")
    bullet: Bullet


class Tailoring(_Strict):
    experience: list[ExperienceSel]
    projects: list[ProjectSel]
    education: list[EducationSel]
    certificates: list[str] = Field(description="Certificate ids, in display order.")
    skills: list[SkillGroupSel]
    reserve: list[ReserveBullet] = Field(description="Extra bullets, best first.")
    changes: list[str] = Field(description="Short notes on what was changed and why.")
    gaps: list[str] = Field(description="Posting requirements with no evidence in the inventory.")


class LetterParagraph(_Strict):
    sources: list[str] = Field(
        description="Inventory section ids this paragraph's facts come from, e.g. ['4.1']."
    )
    en: str | None = Field(description="English text, plain, no LaTeX. Null if English "
                           "was not requested.")
    tr: str | None = Field(description="Turkish text, plain, no LaTeX, first person. Null "
                           "if Turkish was not requested.")


class LearningItem(_Strict):
    en: str = Field(description="Short name as the posting writes it, e.g. 'Kafka'.")
    tr: str = Field(description="Its Turkish name; technology names stay as they are.")


class CoverLetter(_Strict):
    """The body of a cover letter. Greeting, date, heading and sign-off are added in code,
    so the model never writes a name, an address or contact details."""

    paragraphs: list[LetterParagraph] = Field(description="3 or 4 body paragraphs, in order.")
    learning: list[LearningItem] = Field(
        description="Up to 3 things the posting asks for that the candidate does not have. "
        "The tool adds one sentence saying the candidate has not worked with them yet and "
        "is keen to learn them. Empty if nothing important is missing."
    )


LetterLangs = Literal["en", "tr", "both"]


def letter_languages(choice: LetterLangs | None) -> tuple[str, ...]:
    return () if choice is None else ("en", "tr") if choice == "both" else (choice,)


# =======================================================================================
# Request / result files (web app ↔ workflow)
# =======================================================================================


class Posting(BaseModel):
    text: str


class ApplicationRequest(BaseModel):
    schema_version: Literal[1] = 1
    type: Literal["application"] = "application"
    id: str
    # A regenerate takes the posting from the earlier run's folder instead.
    posting: Posting | None = None
    company: str | None = None
    position: str | None = None
    provider: str | None = None
    model: str | None = None
    note: str | None = None
    # Which cover letters to write. Older request files carry a bool: true meant both.
    cover_letter: LetterLangs | None = None
    # The id of an earlier application whose folder this run rebuilds (with a new note).
    regenerates: str | None = None

    @field_validator("cover_letter", mode="before")
    @classmethod
    def _bool_letter(cls, v: object) -> object:
        if v is True:
            return "both"
        return None if v is False else v

    @model_validator(mode="after")
    def _posting_or_regenerates(self) -> ApplicationRequest:
        if self.posting is None and self.regenerates is None:
            raise ValueError("needs a posting, or the id of the run it regenerates")
        return self


class PresetRequest(BaseModel):
    schema_version: Literal[1] = 1
    type: Literal["preset"] = "preset"
    id: str
    presets: list[str] | Literal["stale", "all"]
    provider: str | None = None
    model: str | None = None


class RunResult(BaseModel):
    id: str
    status: Literal["done", "failed"]
    kind: Literal["application", "preset"] = "application"
    folder: str | None = None
    files: dict[str, str] = Field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    cost_usd: float = 0.0
    match_pct: int | None = None
    notices: list[str] = Field(default_factory=list)
    error: str | None = None
    # A preset request builds several presets; each one's own result, keyed by preset id.
    runs: list[RunResult] = Field(default_factory=list)


class PresetManifest(BaseModel):
    preset_id: str
    built_at: str
    provider: str
    model: str
    cost_usd: float
    tool_version: str
    input_hash: str
    inputs: dict[str, str]
    files: dict[str, str] = Field(default_factory=dict)


# =======================================================================================
# Parsed inventory (never sent as-is; see redaction.py)
# =======================================================================================

Status = Literal["shipped", "in-review", "complete", "in-progress", "planned"]
ALLOWED_STATUSES: frozenset[str] = frozenset({"shipped", "in-review", "complete"})


@dataclass
class InvEntry:
    """An experience (`3.n`) or project (`4.n`) section."""

    id: str
    kind: Literal["experience", "project"]
    title: str
    status: str | None = None
    allow_in_progress: bool = False
    link: str | None = None
    stack: list[str] = field(default_factory=list)  # eligible for the heading
    bullets: list[str] = field(default_factory=list)
    do_not_claim: list[str] = field(default_factory=list)
    positive_text: str = ""  # everything that may be cited
    negative_text: str = ""  # "do not" sentences: their numbers are forbidden

    @property
    def usable(self) -> bool:
        if self.kind == "experience":
            return True
        if self.status in ALLOWED_STATUSES:
            return True
        return self.status == "in-progress" and self.allow_in_progress


@dataclass
class InvCertificate:
    id: str
    name: str
    issuer: str
    date_en: str
    date_tr: str
    link: str


@dataclass
class Inventory:
    raw: str
    contact_lines: list[str]
    education_text: str
    courses: list[str]  # English names, parentheticals stripped
    experience: list[InvEntry]
    projects: list[InvEntry]
    certificates: list[InvCertificate]
    skills: list[str]  # canonical names, as written
    skills_text: str
    never_claim: list[str]

    def entry(self, entry_id: str) -> InvEntry | None:
        for e in (*self.experience, *self.projects):
            if e.id == entry_id:
                return e
        return None


# =======================================================================================
# Parsed base resume (one per language)
# =======================================================================================


@dataclass
class BaseEntry:
    """One \\resumeSubheading (experience) or \\resumeProjectHeading (project) block."""

    block: str  # the full original block text
    header: str  # experience: everything up to and including \resumeItemListStart
    footer: str  # experience: the \resumeItemListEnd line
    title_tex: str  # project: inner of \textbf{...}; experience: org
    stack: list[str]
    link: str | None
    link_tex: str  # project: second argument of \resumeProjectHeading (verbatim)
    bullets_tex: list[str]
    indent: str
    item_indent: str


@dataclass
class ListFile:
    """A src/*.tex built from \\resumeSubHeadingListStart ... ListEnd."""

    prefix: str
    head: str  # whitespace between ListStart and the first block
    tail: str  # whitespace between the last block and ListEnd
    suffix: str
    blocks: list[str]


@dataclass
class BaseResume:
    lang: Literal["en", "tr"]
    dir: str
    education_file: str
    courses_label_tex: str  # e.g. "\\textbf{Relevant Courses:}"
    courses: list[str]  # plain text, in base order
    experience: ListFile
    experience_entries: list[BaseEntry]
    projects: ListFile
    project_entries: list[BaseEntry]
    certificates: ListFile
    certificate_names: list[str]
    skills_prefix: str
    skills_suffix: str
    skill_rows: list[tuple[str, str, str]]  # (indent, group_tex, items_tex)
