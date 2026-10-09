"""`tailor init-data-repo`."""

from __future__ import annotations

from pathlib import Path

import yaml

from resume_tailor.cli import main
from resume_tailor.config import load_config
from resume_tailor.scaffold import init_data_repo

REF = "0123456789abcdef0123456789abcdef01234567"


def test_fresh_repo_is_complete_and_valid(tmp_path: Path) -> None:
    repo = tmp_path / "resume-data"
    init_data_repo(repo, tool_repo="someone/resume-tailor", tool_ref=REF)
    for rel in ("base/en/resume.tex", "base/tr/src/projects.tex", "career-inventory.md",
                "config.yml", "presets.yml", "requests/.gitkeep", "results/.gitkeep",
                ".gitignore", "README.md", ".github/workflows/tailor.yml"):
        assert (repo / rel).exists(), rel
    assert not (repo / "fixtures").exists()
    load_config(repo)  # the sample config is valid as-is
    wf = yaml.safe_load((repo / ".github/workflows/tailor.yml").read_text("utf-8"))
    job = wf["jobs"]["tailor"]
    assert job["uses"] == f"someone/resume-tailor/.github/workflows/tailor.yml@{REF}"
    assert job["with"]["tool-ref"] == REF
    assert wf["concurrency"] == {"group": "tailor", "cancel-in-progress": False}
    # PyYAML reads the `on:` key as True
    assert wf[True]["push"]["paths"] == ["requests/**.json"]
    assert "{{TOOL_" not in (repo / ".github/workflows/tailor.yml").read_text("utf-8")


def test_existing_repo_keeps_everything(tmp_path: Path) -> None:
    repo = tmp_path / "resume-data"
    (repo / "results").mkdir(parents=True)
    (repo / "config.yml").write_text("mine: true\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".env\nmy-own-rule\n", encoding="utf-8")
    wf = repo / ".github/workflows/tailor.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("custom\n", encoding="utf-8")
    log = init_data_repo(repo, tool_repo="a/b", tool_ref=REF)
    assert (repo / "config.yml").read_text("utf-8") == "mine: true\n"
    assert wf.read_text("utf-8") == "custom\n"
    gi = (repo / ".gitignore").read_text("utf-8").splitlines()
    assert gi[:2] == [".env", "my-own-rule"] and ".env.*" in gi and gi.count(".env") == 1
    assert any("kept      results/" in line for line in log)
    init_data_repo(repo, tool_repo="a/b", tool_ref="v9", update_workflow=True)
    assert "@v9" in wf.read_text("utf-8")


def test_cli_needs_a_ref_when_not_in_a_checkout(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import resume_tailor.scaffold as scaffold

    monkeypatch.setattr(scaffold, "tool_head", lambda: None)
    assert main(["init-data-repo", str(tmp_path / "d")]) == 2
    assert main(["init-data-repo", str(tmp_path / "d"), "--tool-ref", REF]) == 0
