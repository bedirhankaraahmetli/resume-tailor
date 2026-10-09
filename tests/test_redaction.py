"""Redaction must keep every contact string away from every provider."""

import json
from pathlib import Path

import pytest

from resume_tailor.catalog import Catalog, build_catalog
from resume_tailor.config import load_config
from resume_tailor.llm_input import analyze_call, tailor_call
from resume_tailor.models import Analysis
from resume_tailor.redaction import PLACEHOLDER, RedactionError, assert_clean, redact

from conftest import REAL, SAMPLE, real_data

NAMES = ["Deniz Yılmaz", "Deniz YILMAZ"]
CONTACTS = ["+90 555 010 20 30", "deniz.yilmaz@example.com", "deniz-yilmaz-sample", "Kadıköy"]


@pytest.mark.parametrize("text", [
    "Deniz Yılmaz", "DENİZ YILMAZ", "deniz yilmaz", "Yılmaz'ın projesi", "Deniz'in",
])
def test_name_forms_become_placeholder(text: str) -> None:
    out = redact(text, NAMES)
    assert PLACEHOLDER in out and "ılmaz" not in out.lower() and "deniz" not in out.lower()


def test_scrubs_email_phone_and_urls() -> None:
    text = ("mail deniz.yilmaz@example.com, tel +90 (555) 010-20-30, "
            "https://github.com/deniz-yilmaz-sample/x and linkedin.com/in/deniz-yilmaz-sample")
    out = redact(text, NAMES)
    assert_clean(out, NAMES, CONTACTS)
    assert "[email]" in out and "[phone]" in out and "[link]" in out


def test_keeps_tech_names_and_counts() -> None:
    text = "ASP.NET, Node.js, Socket.io, 10,000 rows, July 2023 – Oct 2023"
    assert redact(text, NAMES) == text


def test_fail_closed_on_leak() -> None:
    with pytest.raises(RedactionError) as e:
        assert_clean("call +90 555 010 20 30", NAMES, CONTACTS)
    assert "555" not in str(e.value)  # the error never echoes the secret


def test_phone_not_assembled_from_unrelated_numbers() -> None:
    assert_clean("90 users, 555 tests, 010 and 20 30", NAMES, CONTACTS)


def _payload(cat: Catalog) -> str:
    a = Analysis.model_validate_json((SAMPLE / "fixtures/analysis.json").read_text("utf-8"))
    posting = "Contact Deniz Yılmaz at deniz.yilmaz@example.com about this role."
    calls = [analyze_call(cat.config, posting),
             tailor_call(cat, analysis=a, posting=posting, note="mention Kadıköy? no")]
    return json.dumps([[c.system, c.user] for c in calls], ensure_ascii=False)


def _all_contacts(cat: Catalog) -> list[str]:
    return [*cat.config.owner.names, *cat.config.owner.contact_strings]


def test_full_payload_is_clean_sample(sample_catalog: Catalog) -> None:
    payload = _payload(sample_catalog)
    for s in _all_contacts(sample_catalog):
        assert s.lower() not in payload.lower(), s
    assert "heading" not in payload.lower() or "\\huge" not in payload.lower()


@real_data
def test_full_payload_is_clean_real() -> None:
    """With the owner's real contact strings from config.yml (never copied here)."""
    assert REAL
    cat = build_catalog(Path(REAL), load_config(Path(REAL)))
    payload = _payload(cat)
    assert_clean(payload, cat.config.owner.names, cat.config.owner.contact_strings)
