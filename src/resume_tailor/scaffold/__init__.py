"""`tailor init-data-repo PATH`: scaffold the private data repo (PROMPT.md §7).

It never overwrites anything. A folder that already holds real data only gains what it is
missing (the caller workflow, `requests/`, `results/`, `.gitignore`), so it is safe to run
on the owner's existing `resume-data`. Data files that are missing are copied from the
fictional sample person, so a fresh repo passes `tailor check` at once and shows the
format to replace.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

TEMPLATES = Path(__file__).parent / "templates"
# Copied from sample-data when missing. Fixtures stay out: --dry-run is for the tool's own
# tests, and a data repo with fixtures would invite confusing them with real runs.
SAMPLE_ITEMS = ("base", "career-inventory.md", "config.yml", "presets.yml")


def _sample_dir() -> Path:
    packaged = Path(__file__).resolve().parents[1] / "_sample"
    if packaged.exists():
        return packaged
    return Path(__file__).resolve().parents[3] / "sample-data"


def tool_head() -> str | None:
    """The commit this tool was installed from, when it runs from a git checkout."""
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def caller_workflow(tool_repo: str, tool_ref: str) -> str:
    text = (TEMPLATES / "tailor.yml").read_text(encoding="utf-8")
    return text.replace("{{TOOL_REPO}}", tool_repo).replace("{{TOOL_REF}}", tool_ref)


def init_data_repo(path: Path, *, tool_repo: str, tool_ref: str,
                   update_workflow: bool = False) -> list[str]:
    """Create what is missing. Returns one line per action, for the CLI to print."""
    log: list[str] = []
    path.mkdir(parents=True, exist_ok=True)

    sample = _sample_dir()
    for item in SAMPLE_ITEMS:
        dest = path / item
        if dest.exists():
            log.append(f"kept      {item}")
            continue
        src = sample / item
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copyfile(src, dest)
        log.append(f"created   {item}  (fictional sample: replace with your own)")

    for d in ("requests", "results"):
        keep = path / d / ".gitkeep"
        if (path / d).exists():
            log.append(f"kept      {d}/")
        else:
            keep.parent.mkdir(parents=True)
            keep.write_text("", encoding="utf-8")
            log.append(f"created   {d}/")

    gitignore = path / ".gitignore"
    wanted = (TEMPLATES / "gitignore").read_text(encoding="utf-8").splitlines()
    have = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    missing = [line for line in wanted if line and not line.startswith("#")
               and line not in have]
    if missing:
        body = "\n".join(have).rstrip()
        add = "\n".join(missing)
        # newline="\n": on Windows write_text would turn every existing line into CRLF.
        gitignore.write_text((body + "\n\n" if body else "") + add + "\n", encoding="utf-8",
                             newline="\n")
        log.append(f"updated   .gitignore (+{len(missing)} line(s))")
    else:
        log.append("kept      .gitignore")

    readme = path / "README.md"
    if not readme.exists():
        shutil.copyfile(TEMPLATES / "README.md", readme)
        log.append("created   README.md")

    wf = path / ".github" / "workflows" / "tailor.yml"
    if wf.exists() and not update_workflow:
        log.append("kept      .github/workflows/tailor.yml (use --update-workflow to replace)")
    else:
        verb = "updated  " if wf.exists() else "created  "
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text(caller_workflow(tool_repo, tool_ref), encoding="utf-8", newline="\n")
        log.append(f"{verb} .github/workflows/tailor.yml (calls {tool_repo}@{tool_ref})")
    return log
