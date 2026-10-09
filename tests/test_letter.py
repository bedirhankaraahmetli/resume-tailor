"""Cover letters: the letter's fact guard and its LaTeX."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from resume_tailor.catalog import Catalog, build_catalog
from resume_tailor.config import load_config
from resume_tailor.guard import check_letter
from resume_tailor.letter import learning_sentence, letter_date, preamble, render_letter
from resume_tailor.models import ApplicationRequest, CoverLetter, LearningItem, letter_languages


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


def _learning(cat: Catalog, letter: CoverLetter, posting: str, *names: str) -> set[str]:
    letter.learning = [LearningItem(en=n, tr=n) for n in names]
    return {str(v) for v in check_letter(cat, letter, ("en", "tr"), posting).violations}


def test_learning_lists_only_real_gaps_from_the_posting(cat: Catalog, letter: CoverLetter,
                                                         sample_dir: Path) -> None:
    posting = (sample_dir / "fixtures/posting.txt").read_text("utf-8")
    # Airflow is asked for and missing; Kubernetes is on the never-claim list, and saying
    # "not yet" about it is true, so it is allowed here and nowhere else.
    assert _learning(cat, letter, posting, "Airflow", "Kubernetes") == set()
    # Python is in the inventory: calling it a gap would be false too.
    assert any("candidate has this" in v for v in _learning(cat, letter, posting, "Python"))
    # Rust is not in the posting.
    assert any("not in the posting" in v for v in _learning(cat, letter, posting, "Rust"))
    assert any("at most 3" in v
               for v in _learning(cat, letter, posting, "Airflow", "AWS", "FastAPI", "Kubernetes"))


def test_a_missing_skill_named_in_a_paragraph_still_fails(cat: Catalog, letter: CoverLetter,
                                                          sample_dir: Path) -> None:
    posting = (sample_dir / "fixtures/posting.txt").read_text("utf-8")
    p = letter.paragraphs[0]
    letter.paragraphs[0] = p.model_copy(update={"en": (p.en or "") + " I use Airflow daily."})
    codes = {v.code for v in check_letter(cat, letter, ("en", "tr"), posting).violations}
    assert "unknown-tech" in codes


def test_the_learning_sentence_is_written_by_code(letter: CoverLetter,
                                                  sample_dir: Path) -> None:
    letter.learning = [LearningItem(en="Airflow", tr="Airflow"),
                       LearningItem(en="system design", tr="sistem tasarımı")]
    assert learning_sentence(letter, "en") == ("I have not worked with Airflow and system "
                                               "design yet, and I am keen to learn them quickly.")
    assert learning_sentence(letter, "tr") == ("Airflow ve sistem tasarımı ile henüz "
                                               "çalışmadım, ancak bunları hızlıca öğrenmeye "
                                               "hazırım.")
    letter.learning = letter.learning[:1]
    base = (sample_dir / "base/en/resume.tex").read_text("utf-8")
    tex = render_letter(base, letter, "en", company=None, position="ML Engineer",
                        signer="Deniz Yılmaz", today=date(2026, 10, 9))
    # Its own paragraph, just before the closing one.
    learn = tex.index("I have not worked with Airflow yet, and I am keen to learn it quickly.")
    assert tex.index("3 regional reports") < learn < tex.index("I would be glad to talk")
    letter.learning = []
    assert learning_sentence(letter, "en") is None


@pytest.mark.parametrize("item", ["3 years of experience", "3+ yıl deneyim",
                                  "Master's degree", "Senior level"])
def test_learning_is_for_skills_not_experience_or_degrees(cat: Catalog, letter: CoverLetter,
                                                          item: str) -> None:
    posting = f"Requirements: {item}, Airflow."
    assert any("only a skill or technology" in v for v in _learning(cat, letter, posting, item))
    assert _learning(cat, letter, posting, "Airflow") == set()
