"""End to end on the sample data. Compiles real PDFs, so it needs pdflatex."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from resume_tailor.build import find_pdflatex
from resume_tailor.config import load_presets
from resume_tailor.pipeline import RunRequest, run
from resume_tailor.presets import status

pytestmark = pytest.mark.skipif(find_pdflatex() is None, reason="pdflatex not installed")


def _dry(data: Path, **kw: object) -> RunRequest:
    return RunRequest(kind="application", request_id="test-1", dry_run=True,
                      posting=(data / "fixtures/posting.txt").read_text("utf-8"), **kw)  # type: ignore[arg-type]


def test_dry_run_end_to_end(sample_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "Job Applications"
    res = run(sample_dir, _dry(sample_dir), out_dir=out, log=lambda _m: None)
    assert res.status == "done", res.error
    folder = "Northwind Labs - Machine Learning Engineer (Junior)"
    assert res.folder == f"applications/{folder}"
    for name in ("Deniz_Yilmaz_Machine_Learning_Engineer_Junior_Resume.pdf",
                 "Deniz_Yilmaz_Machine_Learning_Engineer_Junior_Ozgecmis.pdf"):
        for root in (sample_dir / "applications" / folder, out / folder):
            pdf = root / name
            assert len(PdfReader(pdf).pages) == 1
    text = PdfReader(sample_dir / res.files["tr"]).pages[0].extract_text()
    assert "ğ" in text or "ş" in text  # Turkish letters as single code points
    assert not any(0xFB00 <= ord(c) <= 0xFB06 for c in text)
    report = (sample_dir / res.files["report"]).read_text(encoding="utf-8")
    assert "## Keyword match" in report and "Total cost" in report
    rows = list(csv.DictReader((sample_dir / "applications.csv").open(encoding="utf-8")))
    assert rows[0]["folder"] == folder and rows[0]["source"] == "tailored"
    result = json.loads((sample_dir / "results/test-1.json").read_text(encoding="utf-8"))
    assert result["status"] == "done"


def test_second_run_gets_a_numbered_folder(sample_dir: Path) -> None:
    run(sample_dir, _dry(sample_dir), out_dir=None, log=lambda _m: None)
    res = run(sample_dir, _dry(sample_dir), out_dir=None, log=lambda _m: None)
    assert res.folder is not None and res.folder.endswith("(Junior) (2)")


def test_manual_position_wins(sample_dir: Path) -> None:
    res = run(sample_dir, _dry(sample_dir, company="Northwind", position="Veri Bilimci"),
              out_dir=None, log=lambda _m: None)
    assert res.folder == "applications/Northwind - Veri Bilimci"
    assert res.files["tr"].endswith("Deniz_Yilmaz_Veri_Bilimci_Ozgecmis.pdf")


def test_guard_failure_fails_the_run_readably(sample_dir: Path) -> None:
    fx = sample_dir / "fixtures/tailoring.json"
    fx.write_text(fx.read_text(encoding="utf-8").replace("0.84", "0.97"), encoding="utf-8")
    res = run(sample_dir, _dry(sample_dir), out_dir=None, log=lambda _m: None)
    assert res.status == "failed"
    assert res.error and "fact guard failed" in res.error and "0.97" in res.error


def test_preset_build_writes_manifest_and_skips_csv(sample_dir: Path, tmp_path: Path) -> None:
    from resume_tailor.models import Tailoring
    from resume_tailor.providers.base import LLMCall, LLMResponse, Usage

    tailoring = Tailoring.model_validate_json(
        (sample_dir / "fixtures/tailoring.json").read_text("utf-8")).model_dump_json()

    class Canned:
        name = "anthropic"

        def available(self) -> bool:
            return True

        def complete(self, call: LLMCall) -> LLMResponse:
            return LLMResponse(tailoring, Usage(1000, 500), "anthropic", "claude-sonnet-5-5",
                               0.0070)

    preset = load_presets(sample_dir).presets[0]
    req = RunRequest(kind="preset", request_id="p-1", preset=preset)
    res = run(sample_dir, req, out_dir=tmp_path, providers={"anthropic": Canned()},
              log=lambda _m: None)
    assert res.status == "done", res.error
    assert (tmp_path / "_Presets" / preset.folder / "Deniz_Yilmaz_Data_Scientist_Resume.pdf").exists()
    assert status(sample_dir, preset) == "up to date"
    assert not (sample_dir / "applications.csv").exists()
    usage = list(csv.DictReader((sample_dir / "usage.csv").open(encoding="utf-8")))
    assert usage[0]["kind"] == "preset" and float(usage[0]["cost_usd"]) == pytest.approx(0.007)
