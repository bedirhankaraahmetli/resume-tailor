"""Cover letters: the letter's fact guard and its LaTeX."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from resume_tailor.catalog import Catalog, build_catalog
from resume_tailor.config import load_config
from resume_tailor.guard import check_letter
from resume_tailor.letter import letter_date, preamble, render_letter
from resume_tailor.models import ApplicationRequest, CoverLetter, letter_languages


@pytest.fixture
def cat(sample_dir: Path) -> Catalog:
    return build_catalog(sample_dir, load_config(sample_dir))


@pytest.fixture
def letter(sample_dir: Path) -> CoverLetter:
    return CoverLetter.model_validate_json(
        (sample_dir / "fixtures/letter.json").read_text("utf-8"))


def _codes(cat: Catalog, letter: CoverLetter, langs: tuple[str, ...] = ("en", "tr")) -> set[str]:
    return {v.code for v in check_letter(cat, letter, langs).violations}


def test_the_sample_letter_passes(cat: Catalog, letter: CoverLetter) -> None:
    assert check_letter(cat, letter, ("en", "tr")).ok


def test_numbers_must_be_in_the_cited_sources(cat: Catalog, letter: CoverLetter) -> None:
    p = letter.paragraphs[1]
    letter.paragraphs[1] = p.model_copy(update={"en": (p.en or "") + " It saved 40% of costs."})
    assert "number" in _codes(cat, letter)


def test_a_ruled_out_number_and_a_never_claim_term_fail(cat: Catalog,
                                                        letter: CoverLetter) -> None:
    p = letter.paragraphs[1]
    letter.paragraphs[1] = p.model_copy(update={
        "en": (p.en or "").replace("0.84", "0.97") + " I also ran it on Kubernetes."})
    assert {"forbidden-number", "never-claim"} <= _codes(cat, letter)


def test_unusable_projects_links_and_missing_languages(cat: Catalog,
                                                       letter: CoverLetter) -> None:
    p = letter.paragraphs[0]
    letter.paragraphs[0] = p.model_copy(update={"sources": ["4.9"], "tr": None,
                                               "en": "See https://example.com"})
    codes = _codes(cat, letter)
    assert {"sources", "contact", "empty"} <= codes
    # English only: a missing Turkish text is fine.
    assert "empty" not in _codes(cat, letter, ("en",))


def test_length_is_capped(cat: Catalog, letter: CoverLetter) -> None:
    p = letter.paragraphs[3]
    letter.paragraphs[3] = p.model_copy(update={"en": "word " * 400})
    assert "length" in _codes(cat, letter, ("en",))


def test_render_uses_the_base_preamble_and_heading(sample_dir: Path, letter: CoverLetter) -> None:
    base = (sample_dir / "base/tr/resume.tex").read_text("utf-8")
    tex = render_letter(base, letter, "tr", company="Northwind Labs",
                        position="Junior ML Engineer", signer="Deniz Yılmaz",
                        today=date(2026, 10, 9))
    assert tex.startswith(preamble(base))
    assert "\\input{src/heading}" in tex and "9 Ekim 2026" in tex
    assert "Sayın Northwind Labs İşe Alım Ekibi," in tex and "Saygılarımla," in tex
    assert "Churn Radar" in tex and "Northwind Labs'teki" in tex
    en = render_letter(base, letter, "en", company=None, position="R&D Engineer",
                       signer="Deniz Yılmaz", today=date(2026, 10, 9))
    assert "Dear Hiring Team," in en and "Application for R\\&D Engineer" in en
    assert "October 9, 2026" in en


def test_dates_and_language_choices() -> None:
    assert letter_date(date(2026, 2, 1), "tr") == "1 Şubat 2026"
    assert letter_languages(None) == () and letter_languages("both") == ("en", "tr")
    req = ApplicationRequest.model_validate({"id": "x", "posting": {"text": "p"},
                                             "cover_letter": False})
    assert req.cover_letter is None
