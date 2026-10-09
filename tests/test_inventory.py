from pathlib import Path

from resume_tailor.inventory import parse_inventory, split_terms, strip_contact_section

from conftest import REAL, SAMPLE, real_data


def _sample() -> str:
    return (SAMPLE / "career-inventory.md").read_text(encoding="utf-8")


def test_parses_sections() -> None:
    inv = parse_inventory(_sample())
    assert [e.id for e in inv.experience] == ["3.1", "3.2"]
    assert [p.id for p in inv.projects] == ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6"]
    assert inv.courses[:2] == ["Machine Learning", "Databases"]  # parentheticals stripped
    assert [c.id for c in inv.certificates] == ["5.1", "5.2"]
    assert inv.certificates[1].date_tr == "Oca 2023"


def test_statuses_and_usability() -> None:
    inv = parse_inventory(_sample())
    by = {p.id: p for p in inv.projects}
    assert by["4.1"].status == "shipped" and by["4.1"].usable
    assert by["4.5"].status == "in-progress" and by["4.5"].allow_in_progress and by["4.5"].usable
    assert by["4.6"].status == "planned" and not by["4.6"].usable


def test_in_progress_without_permission_is_not_usable() -> None:
    text = _sample().replace("- Resume use: allowed (label as in progress)\n", "")
    inv = parse_inventory(text)
    assert not next(p for p in inv.projects if p.id == "4.5").usable


def test_negative_sentences_are_separated() -> None:
    inv = parse_inventory(_sample())
    churn = next(p for p in inv.projects if p.id == "4.2")
    assert "0.97" in churn.negative_text
    assert "0.97" not in churn.positive_text
    assert "0.84" in churn.positive_text


def test_stack_lines_are_not_citable_text() -> None:
    inv = parse_inventory(_sample())
    ledger = next(p for p in inv.projects if p.id == "4.3")
    assert "Java 17" in ledger.stack and "Java" in ledger.stack
    assert "Java 17" not in ledger.positive_text


def test_bullets_and_do_not_claim() -> None:
    inv = parse_inventory(_sample())
    parkly = inv.projects[0]
    assert len(parkly.bullets) == 3
    assert parkly.do_not_claim == ["download numbers or ratings (not tracked)."]


def test_skills_and_never_claim() -> None:
    inv = parse_inventory(_sample())
    assert {"Swift", "SwiftUI", "Unit testing", "XCTest", "JUnit 5", "JUnit"} <= set(inv.skills)
    assert inv.never_claim == ["Kubernetes", "AWS", "team leadership", "Android"]


def test_split_terms() -> None:
    assert split_terms("Swift (AlarmKit, App Intents), Drift + SQLCipher, Java 21") == [
        "Swift", "AlarmKit", "App Intents", "Drift", "SQLCipher", "Java 21", "Java",
    ]


def test_split_terms_keeps_a_leading_dot() -> None:
    assert split_terms(".NET Framework, Tkinter.") == [".NET Framework", "Tkinter"]
    assert split_terms("Object-oriented programming (OOP)") == [
        "Object-oriented programming", "OOP"]


def test_strip_contact_section() -> None:
    out = strip_contact_section(_sample())
    assert "## 1." not in out and "555 010" not in out and "## 2. Education" in out


@real_data
def test_real_inventory_parses() -> None:
    assert REAL
    inv = parse_inventory((Path(REAL) / "career-inventory.md").read_text(encoding="utf-8"))
    assert inv.experience and inv.projects and inv.certificates and inv.skills
    planned = [p for p in inv.projects if p.status == "planned"]
    assert all(not p.usable for p in planned)
