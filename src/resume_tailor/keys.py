"""Add, change, check and remove provider credentials (`tailor keys …`).

Keys are kept in a `.env` file next to where the CLI runs (never committed). They can
also be pushed to GitHub as Actions secrets, which is where the workflow reads them;
GitHub never lets a secret be read back, so this module never prints a full key either.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROVIDER_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "claude-code": "CLAUDE_CODE_OAUTH_TOKEN",  # CI only; locally Claude Code uses its login
}
_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


class KeyError_(ValueError):
    pass


def mask(value: str) -> str:
    if len(value) <= 12:
        return "•" * len(value)
    return f"{value[:7]}…{value[-4:]}"


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = _LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def write_env(path: Path, var: str, value: str | None) -> None:
    """Set (or with None, remove) one variable, keeping every other line and comment."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        m = _LINE.match(line)
        if m and m.group(1) == var:
            if value is not None and not done:
                out.append(f"{var}={value}")
                done = True
            continue
        out.append(line)
    if value is not None and not done:
        out.append(f"{var}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def validate_value(var: str, value: str) -> None:
    if not value or re.search(r"\s", value):
        raise KeyError_("the key is empty or contains spaces")
    if var == "ANTHROPIC_API_KEY" and not value.startswith("sk-ant-"):
        raise KeyError_("Claude API keys start with 'sk-ant-'")


@dataclass
class KeyStatus:
    provider: str
    var: str
    source: str  # "environment", ".env" or "missing"
    masked: str


def status(env_file: Path) -> list[KeyStatus]:
    file_vals = read_env(env_file)
    rows = []
    for provider, var in PROVIDER_VARS.items():
        if file_vals.get(var):
            rows.append(KeyStatus(provider, var, ".env", mask(file_vals[var])))
        elif os.environ.get(var):
            rows.append(KeyStatus(provider, var, "environment", mask(os.environ[var])))
        else:
            rows.append(KeyStatus(provider, var, "missing", ""))
    return rows


def check_live(provider: str, value: str) -> tuple[bool, str]:
    """Verify a key with a free call (listing models costs no tokens)."""
    try:
        if provider == "anthropic":
            import anthropic

            try:
                anthropic.Anthropic(api_key=value, max_retries=1).models.list(limit=1)
            except anthropic.AuthenticationError:
                return False, "rejected: the key is invalid, expired or revoked"
            except anthropic.PermissionDeniedError:
                return False, "rejected: the key has no permission"
            return True, "accepted by the Claude API"
        if provider == "gemini":
            from google import genai

            next(iter(genai.Client(api_key=value).models.list()))
            return True, "accepted by the Gemini API"
    except Exception as e:  # network errors, SDK errors: report, never crash
        return False, f"could not verify ({type(e).__name__})"
    return True, "not checked (only used in GitHub Actions)"


def push_to_github(var: str, value: str, repo: str) -> None:
    """Store as an Actions secret with the GitHub CLI; the value goes over stdin only."""
    gh = shutil.which("gh")
    if gh is None:
        raise KeyError_("GitHub CLI (gh) not found")
    proc = subprocess.run([gh, "secret", "set", var, "--repo", repo], input=value,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise KeyError_(f"gh secret set failed: {proc.stderr.strip()[:200]}")
