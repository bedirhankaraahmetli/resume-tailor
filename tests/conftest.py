"""Test setup.

The suite must never reach a live LLM (CLAUDE.md §3): sockets are blocked and provider
credentials are removed for every test. The one live smoke test needs RT_LIVE_SMOKE=1.

Tests against the owner's real data run only when RT_DATA_DIR points at it; the real
data never enters this repository.
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

import pytest

from resume_tailor.catalog import Catalog, build_catalog
from resume_tailor.config import load_config

SAMPLE = Path(__file__).resolve().parents[1] / "sample-data"
REAL = os.environ.get("RT_DATA_DIR")

real_data = pytest.mark.skipif(not REAL, reason="set RT_DATA_DIR to run against real data")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY",
                "CLAUDE_CODE_OAUTH_TOKEN"):
        if "live" not in request.keywords:
            monkeypatch.delenv(key, raising=False)
    if "live" in request.keywords:
        return

    def refuse(*_a: object, **_k: object) -> None:
        raise RuntimeError("tests must not reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "data"
    shutil.copytree(SAMPLE, dest)
    return dest


@pytest.fixture(scope="session")
def sample_catalog() -> Catalog:
    return build_catalog(SAMPLE, load_config(SAMPLE))


@pytest.fixture(scope="session")
def real_catalog() -> Catalog:
    assert REAL
    return build_catalog(Path(REAL), load_config(Path(REAL)))
