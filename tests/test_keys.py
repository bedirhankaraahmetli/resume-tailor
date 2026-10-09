import io
from pathlib import Path

import pytest

from resume_tailor import cli
from resume_tailor.keys import KeyError_, mask, read_env, status, validate_value, write_env

KEY = "sk-ant-api03-" + "x" * 80 + "WwAA"


def test_write_env_keeps_other_lines(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("# my keys\nGEMINI_API_KEY=g1\nANTHROPIC_API_KEY=old\n", encoding="utf-8")
    write_env(f, "ANTHROPIC_API_KEY", "new")
    assert f.read_text(encoding="utf-8") == "# my keys\nGEMINI_API_KEY=g1\nANTHROPIC_API_KEY=new\n"
    write_env(f, "GEMINI_API_KEY", None)
    assert read_env(f) == {"ANTHROPIC_API_KEY": "new"}


def test_read_env_tolerates_bom_and_quotes(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_bytes("﻿ANTHROPIC_API_KEY=\"abc\"\n".encode())
    assert read_env(f) == {"ANTHROPIC_API_KEY": "abc"}


def test_mask_never_shows_the_middle() -> None:
    m = mask(KEY)
    assert m == "sk-ant-…WwAA" and "xxxx" not in m


def test_validate_value() -> None:
    validate_value("ANTHROPIC_API_KEY", KEY)
    with pytest.raises(KeyError_):
        validate_value("ANTHROPIC_API_KEY", "AIza-not-a-claude-key")
    with pytest.raises(KeyError_):
        validate_value("GEMINI_API_KEY", "has space")


def test_status_reports_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / ".env"
    write_env(f, "ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "y" * 30)
    rows = {r.provider: r for r in status(f)}
    assert rows["anthropic"].source == ".env" and rows["anthropic"].masked == "sk-ant-…WwAA"
    assert rows["gemini"].source == "environment"
    assert rows["claude-code"].source == "missing"


def test_cli_set_and_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                            capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / ".env"
    monkeypatch.setattr("sys.stdin", io.StringIO(KEY + "\n"))
    rc = cli.main(["keys", "set", "anthropic", "--stdin", "--no-check", "--env-file", str(f)])
    assert rc == 0 and read_env(f)["ANTHROPIC_API_KEY"] == KEY
    out = capsys.readouterr().out
    assert KEY not in out and "sk-ant-…WwAA" in out  # the full key is never printed
    assert cli.main(["keys", "remove", "anthropic", "--env-file", str(f)]) == 0
    assert "ANTHROPIC_API_KEY" not in read_env(f)


def test_cli_rejects_malformed_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / ".env"
    monkeypatch.setattr("sys.stdin", io.StringIO("not-a-key\n"))
    rc = cli.main(["keys", "set", "anthropic", "--stdin", "--no-check", "--env-file", str(f)])
    assert rc == 2 and not f.exists()
