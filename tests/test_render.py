"""Layout safety: the identity round-trip and golden files."""

import os
from pathlib import Path

import pytest

from resume_tailor.catalog import Catalog
from resume_tailor.identity import identity_tailoring, normalize_tex
from resume_tailor.models import Tailoring
from resume_tailor.render import RenderError, render_all

from conftest import REAL, SAMPLE, real_data

GOLDEN = Path(__file__).parent / "golden"


def _assert_identity(cat: Catalog, data_dir: Path) -> None:
    t = identity_tailoring(cat)
    for lang in ("en", "tr"):
        for rel, txt in render_all(cat, t, lang).items():
            orig = (data_dir / "base" / lang / rel).read_text(encoding="utf-8")
            assert normalize_tex(txt) == normalize_tex(orig), f"{lang}/{rel}"


def test_identity_round_trip_sample(sample_catalog: Catalog) -> None:
    """Rendering the base's own content reproduces the base: the layout cannot drift."""
    _assert_identity(sample_catalog, SAMPLE)


@real_data
def test_identity_round_trip_real(real_catalog: Catalog) -> None:
    assert REAL
    _assert_identity(real_catalog, Path(REAL))


def _fixture() -> Tailoring:
    return Tailoring.model_validate_json(
        (SAMPLE / "fixtures/tailoring.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_golden(sample_catalog: Catalog, lang: str) -> None:
    out = render_all(sample_catalog, _fixture(), lang)
    for rel, txt in out.items():
        path = GOLDEN / lang / rel
        if os.environ.get("UPDATE_GOLDEN"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(txt, encoding="utf-8", newline="\n")
        assert txt == path.read_text(encoding="utf-8"), f"golden mismatch: {lang}/{rel}"


def test_non_base_project_uses_given_titles_and_inventory_link(sample_catalog: Catalog) -> None:
    out = render_all(sample_catalog, _fixture(), "tr")["src/projects.tex"]
    assert r"\textbf{Tarif Önerici -- PyTorch Öneri Sistemi}" in out
    assert r"\href{https://github.com/deniz-yilmaz-sample/recipe-recommender}" in out


def test_heading_and_contact_are_never_rendered(sample_catalog: Catalog) -> None:
    out = render_all(sample_catalog, _fixture(), "en")
    assert "src/heading.tex" not in out


def test_in_progress_project_is_labelled(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].id = "4.5"
    t.projects[0].title_en, t.projects[0].title_tr = "Pixel Garden -- Garden Game", "Pixel Garden"
    en = render_all(sample_catalog, t, "en")["src/projects.tex"]
    tr = render_all(sample_catalog, t, "tr")["src/projects.tex"]
    assert "Garden Game (In Progress)" in en and "Pixel Garden (Devam Ediyor)" in tr


def test_unknown_course_is_refused(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.education[0].courses.append("Quantum Basket Weaving")
    with pytest.raises(RenderError):
        render_all(sample_catalog, t, "en")


def test_llm_text_is_escaped(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].bullets[0].en = r"Owned 100% of it & \input{x}"
    out = render_all(sample_catalog, t, "en")["src/projects.tex"]
    assert r"Owned 100\% of it \& \textbackslash{}input\{x\}" in out
