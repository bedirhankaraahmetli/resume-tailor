"""The fact guard: one test per rule."""

from collections.abc import Callable

import pytest

from resume_tailor.catalog import Catalog
from resume_tailor.guard import check
from resume_tailor.identity import identity_tailoring
from resume_tailor.models import Bullet, ProjectSel, ReserveBullet, Tailoring

from conftest import SAMPLE


def _fixture() -> Tailoring:
    return Tailoring.model_validate_json(
        (SAMPLE / "fixtures/tailoring.json").read_text(encoding="utf-8"))


def codes(cat: Catalog, t: Tailoring) -> list[str]:
    return [v.code for v in check(cat, t).violations]


def test_fixture_and_identity_pass(sample_catalog: Catalog) -> None:
    assert check(sample_catalog, _fixture()).ok
    assert check(sample_catalog, identity_tailoring(sample_catalog)).ok


def _edit_bullet(text_en: str | None = None, text_tr: str | None = None
                 ) -> Callable[[Tailoring], None]:
    def f(t: Tailoring) -> None:
        b = t.projects[0].bullets[0]
        if text_en is not None:
            b.en = text_en
        if text_tr is not None:
            b.tr = text_tr
    return f


@pytest.mark.parametrize("mutate,code", [
    # numbers must appear in the cited sources
    (_edit_bullet("Reached an ROC AUC of 0.91."), "number"),
    (_edit_bullet(text_tr="Üç modeli karşılaştırdım."), "number"),
    (_edit_bullet("Predicted churn on 7,500 rows."), "number"),
    # a number in a "do not" sentence is forbidden even though it is in the file
    (_edit_bullet("Reached a ROC AUC of 0.97."), "forbidden-number"),
    # never-claim list, in English and Turkish
    (_edit_bullet("Deployed the model on AWS."), "never-claim"),
    (_edit_bullet(text_tr="Takım liderliği yaptım."), "never-claim"),
    # technologies the inventory never mentions
    (_edit_bullet("Orchestrated training with Airflow."), "unknown-tech"),
    (_edit_bullet(text_tr="Modeli FastAPI ile sundum."), "unknown-tech"),
])
def test_bullet_rules(sample_catalog: Catalog, mutate: Callable[[Tailoring], None],
                      code: str) -> None:
    t = _fixture()
    mutate(t)
    assert code in codes(sample_catalog, t)


def test_versioned_names_are_not_counts(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[2].bullets[0].en = "Built it with Java 17 and Spring Boot 3, tested with JUnit 5."
    assert check(sample_catalog, t).ok


def test_spelled_numbers_from_source_are_fine(sample_catalog: Catalog) -> None:
    t = _fixture()  # "five strongest churn drivers" / "beş faktör" is in the fixture
    assert "beş" in t.projects[0].bullets[2].tr
    assert check(sample_catalog, t).ok


def test_experience_never_dropped(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.experience.pop()
    assert "experience" in codes(sample_catalog, t)


def test_minimum_projects(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects = t.projects[:2]
    assert "projects" in codes(sample_catalog, t)


def test_planned_project_rejected(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects.append(ProjectSel(id="4.6", title_en="Weather Bot", title_tr="Hava Botu",
                                 stack=["Python"], bullets=[
                                     Bullet(sources=["4.6"], priority=1, en="x", tr="y")]))
    assert "status" in codes(sample_catalog, t)


def test_unknown_project_id(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].id = "4.99"
    assert "unknown-id" in codes(sample_catalog, t)


def test_stack_must_come_from_that_project(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].stack.append("PyTorch")  # PyTorch is real, but not Churn Radar's
    assert "stack" in codes(sample_catalog, t)


def test_stack_limit(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].stack = ["Python", "Pandas", "Scikit-learn", "XGBoost", "SHAP",
                           "Matplotlib", "Python", "Pandas"]
    assert "stack" in codes(sample_catalog, t)


def test_skills_need_evidence(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.skills[0].items.append("Kubernetes")
    assert "skill" in codes(sample_catalog, t)


def test_unknown_skill_group(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.skills[0].group = "cloud"
    assert "skill-group" in codes(sample_catalog, t)


def test_course_must_exist(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.education[0].courses.append("Deep Learning")
    assert "course" in codes(sample_catalog, t)


def test_unknown_source(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].bullets[0].sources = ["9.9"]
    assert "sources" in codes(sample_catalog, t)


def test_non_base_project_needs_titles(sample_catalog: Catalog) -> None:
    t = _fixture()
    rec = next(p for p in t.projects if p.id == "4.4")
    rec.title_tr = None
    assert "title" in codes(sample_catalog, t)


def test_reserve_is_checked_too(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.reserve.append(ReserveBullet(parent="4.1", bullet=Bullet(
        sources=["4.1"], priority=5, en="Reached 1 million downloads.", tr="1 milyon indirme.")))
    assert "number" in codes(sample_catalog, t)


def test_turkish_passive_voice_warns(sample_catalog: Catalog) -> None:
    t = _fixture()
    t.projects[0].bullets[0].tr = "Model XGBoost ile geliştirildi."
    r = check(sample_catalog, t)
    assert any("passive" in w for w in r.warnings)
