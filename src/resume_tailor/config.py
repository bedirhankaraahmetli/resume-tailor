"""`config.yml` and `presets.yml` from the data repo.

Model ids and prices live here, never in code (CLAUDE.md §3): Anthropic renames and
reprices models, and the owner must be able to switch `tailor_model` with one line.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Owner(_M):
    slug: str = Field(description="File-name prefix, e.g. 'Jane_Doe'.")
    names: list[str] = Field(description="Every written form of the owner's name.")
    email: str
    contact_strings: list[str] = Field(
        default_factory=list,
        description="Phone, email, profile URLs, usernames, address: anything that must "
        "never reach an LLM. Redaction aborts if one survives.",
    )


class AnthropicCfg(_M):
    analyze_model: str = "claude-haiku-4-5"
    tailor_model: str = "claude-sonnet-5-5"
    analyze_effort: str | None = None  # Haiku 4.5 rejects `effort`
    tailor_effort: str | None = "medium"
    max_tokens: int = 16000
    prompt_cache: bool = True


class ClaudeCodeCfg(_M):
    model: str = "sonnet"
    timeout_s: int = 900
    executable: str | None = None


class GeminiCfg(_M):
    model: str = "gemini-3.8-flash"
    thinking_level: str | None = "low"
    max_retries: int = 3


class Providers(_M):
    order: list[str] = Field(default_factory=lambda: ["anthropic", "claude-code", "gemini"])
    anthropic: AnthropicCfg = Field(default_factory=AnthropicCfg)
    claude_code: ClaudeCodeCfg = Field(default_factory=ClaudeCodeCfg, alias="claude-code")
    gemini: GeminiCfg = Field(default_factory=GeminiCfg)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Price(_M):
    input: float
    output: float
    cache_write: float
    cache_read: float


class Pricing(_M):
    as_of: str
    source: str
    models: dict[str, Price]


class SkillGroup(_M):
    id: str
    en: str
    tr: str


class ResumeCfg(_M):
    min_projects: int = 3
    max_stack_items: int = 7
    fill_threshold: float = 0.12
    fixed_skill_rows: int = 1
    min_courses: int = 4
    in_progress_label: dict[str, str] = Field(
        default_factory=lambda: {"en": "In Progress", "tr": "Devam Ediyor"}
    )
    course_names_tr: dict[str, str] = Field(default_factory=dict)
    skill_names_tr: dict[str, str] = Field(default_factory=dict)
    extra_skill_groups: list[SkillGroup] = Field(default_factory=list)
    never_claim_tr: list[str] = Field(default_factory=list)


class Config(_M):
    owner: Owner
    providers: Providers = Field(default_factory=Providers)
    pricing: Pricing
    monthly_budget_usd: float = 5.0
    estimated_run_cost_usd: float = 0.25
    resume: ResumeCfg = Field(default_factory=ResumeCfg)


class Preset(_M):
    id: str
    folder: str
    position: str
    focus: str


class Presets(_M):
    presets: list[Preset] = Field(default_factory=list)


def load_config(data_dir: Path) -> Config:
    raw = yaml.safe_load((data_dir / "config.yml").read_text(encoding="utf-8")) or {}
    return Config.model_validate(raw)


def load_presets(data_dir: Path) -> Presets:
    path = data_dir / "presets.yml"
    if not path.exists():
        return Presets()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Presets.model_validate(raw)
