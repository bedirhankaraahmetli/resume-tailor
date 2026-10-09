"""The one-page fitting loop, with a fake compiler (no TeX needed)."""

import pytest

from resume_tailor.build import PdfInfo
from resume_tailor.fit import FitError, fit
from resume_tailor.models import Tailoring

from conftest import SAMPLE


def _fixture() -> Tailoring:
    return Tailoring.model_validate_json(
        (SAMPLE / "fixtures/tailoring.json").read_text(encoding="utf-8"))


def lines(t: Tailoring) -> int:
    return (sum(len(e.bullets) for e in t.experience)
            + sum(len(p.bullets) + 1 for p in t.projects)
            + len(t.certificates) + len(t.education[0].courses) // 3)


class FakeTeX:
    """One page holds `capacity` lines; Turkish takes `tr_extra` more lines than English."""

    def __init__(self, capacity: int, tr_extra: int = 0, wide: dict[str, int] | None = None):
        self.capacity, self.tr_extra, self.wide = capacity, tr_extra, wide or {}
        self.calls = 0

    def __call__(self, lang: str, t: Tailoring) -> PdfInfo:
        self.calls += 1
        n = lines(t) + (self.tr_extra if lang == "tr" else 0)
        pages = 1 if n <= self.capacity else 2
        empty = max(0.0, (self.capacity - n) / self.capacity)
        over = [p.id for p in t.projects if len(p.stack) > self.wide.get(p.id, 99)]
        return PdfInfo(pages, empty, "", overflow_projects=over)


def run(t: Tailoring, tex: FakeTeX, threshold: float = 0.12):  # type: ignore[no-untyped-def]
    return fit(t, tex, min_projects=3, min_courses=4, fill_threshold=threshold)


def test_fits_without_changes() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t)))
    assert r.log == [] and r.tailoring.projects == t.projects


def test_drops_highest_priority_number_first() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t) - 1))
    assert r.log == ["dropped bullet 2 of 4.3 (priority 4)"]


def test_joint_fit_uses_the_longer_language() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t), tr_extra=2))
    assert len(r.log) == 2  # English fit already; Turkish forced two drops for both
    assert all(i.pages == 1 for i in r.info.values())


def test_keeps_one_bullet_per_entry_then_drops_projects() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t) - 6))
    assert all(len(e.bullets) >= 1 for e in r.tailoring.experience)
    assert all(len(p.bullets) >= 1 for p in r.tailoring.projects)
    assert any(x.startswith("dropped project") for x in r.log)
    assert len(r.tailoring.projects) >= 3


def test_never_drops_experience() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t) - 7))  # the tightest feasible page
    assert [e.id for e in r.tailoring.experience] == ["3.1", "3.2"]


def test_fails_clearly_when_impossible() -> None:
    with pytest.raises(FitError, match="cannot fit on one page"):
        run(_fixture(), FakeTeX(capacity=3))


def test_adds_reserve_when_both_have_room() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t) + 20))
    assert "added reserve bullet to 4.1" in r.log


def test_no_reserve_when_one_language_is_tight() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t) + 20, tr_extra=19))
    assert not any("reserve" in x for x in r.log)


def test_wide_heading_loses_trailing_stack_items() -> None:
    t = _fixture()
    r = run(t, FakeTeX(capacity=lines(t), wide={"4.2": 3}))
    churn = next(p for p in r.tailoring.projects if p.id == "4.2")
    assert churn.stack == ["Python", "XGBoost", "Scikit-learn"]
    assert r.log[0] == "heading of 4.2 too wide: dropped stack item 'Pandas'"


def test_is_deterministic() -> None:
    a = run(_fixture(), FakeTeX(capacity=lines(_fixture()) - 4))
    b = run(_fixture(), FakeTeX(capacity=lines(_fixture()) - 4))
    assert a.log == b.log and a.tailoring == b.tailoring
