from pathlib import Path

from resume_tailor.checks import ats_check, keyword_report
from resume_tailor.config import load_presets
from resume_tailor.models import Analysis
from resume_tailor.presets import combined_hash, input_hashes, status, write_manifest

from conftest import SAMPLE

ANALYSIS = Analysis.model_validate_json((SAMPLE / "fixtures/analysis.json").read_text("utf-8"))


def test_ats_flags_ligatures_and_detached_accents() -> None:
    r = ats_check("Deniz YILMAZ deniz.yilmaz@example.com ﬁltering g˘", lang="en",
                  names=["Deniz Yılmaz"], email="deniz.yilmaz@example.com")
    assert any("ligature" in e for e in r.errors) and any("detached" in e for e in r.errors)


def test_ats_requires_name_and_email() -> None:
    r = ats_check("nothing here", lang="tr", names=["Deniz Yılmaz"], email="d@example.com")
    assert len(r.errors) == 2


def test_ats_tolerates_kerning_spaces() -> None:
    """pypdf splits 'PyTorch' as 'PyT orch' at kerning pairs; that is not a missing word."""
    r = ats_check("DENİZ YILMAZ deniz.yilmaz@example.com PyT orch", lang="en",
                  names=["Deniz Yılmaz"], email="deniz.yilmaz@example.com",
                  must_have=[["PyTorch"]])
    assert r.errors == [] and r.warnings == []


def test_keyword_report_splits_present_evidence_and_gaps() -> None:
    page = "Python Pandas SQL machine learning XGBoost classification"
    evidence = "Python Pandas SQL XGBoost PyTorch Docker Git SHAP"
    k = keyword_report(ANALYSIS, page, evidence)
    assert {"Python", "Pandas", "SQL", "machine learning", "XGBoost"} <= set(k.present)
    assert "PyTorch" in k.missing_with_evidence
    assert {"Kubernetes", "AWS", "Airflow"} <= set(k.gaps)
    assert k.match_pct == round(100 * len(k.present) / len(ANALYSIS.keywords))


def test_turkish_synonym_counts_as_present() -> None:
    k = keyword_report(ANALYSIS, "MAKİNE ÖĞRENMESİ ve sınıflandırma", "")
    assert "machine learning" in k.present and "classification" in k.present


def test_soft_match_drops_generic_words_but_keeps_the_phrase() -> None:
    from resume_tailor.checks import soft_match
    from resume_tailor.text import fold

    ios = fold("Built a privacy-first iOS and Android app")
    assert soft_match(ios, "iOS development") and soft_match(ios, "Android development")
    assert soft_match(fold("Enforced a layered architecture"), "Software architecture")
    # what is left must still be a phrase: these are not evidence
    assert not soft_match(fold("UI design and optimization in Unity"), "Performance optimization")
    assert not soft_match(fold("Wrote code. Status: In Review"), "Code review")
    assert not soft_match(fold("game mechanics, UI design"), "Game design")
    # a term that is only generic words never soft-matches
    assert not soft_match(fold("software"), "Software development")


# ---- presets ------------------------------------------------------------------------------


def test_preset_staleness(sample_dir: Path) -> None:
    p = load_presets(sample_dir).presets[0]
    assert status(sample_dir, p) == "never built"
    write_manifest(sample_dir, p, "anthropic", "m", 0.1, {}, "0.1.0")
    assert status(sample_dir, p) == "up to date"
    inv = sample_dir / "career-inventory.md"
    inv.write_text(inv.read_text(encoding="utf-8") + "\n- new fact\n", encoding="utf-8")
    assert status(sample_dir, p) == "outdated"


def test_preset_hash_ignores_line_endings(sample_dir: Path) -> None:
    p = load_presets(sample_dir).presets[0]
    before = combined_hash(input_hashes(sample_dir, p))
    f = sample_dir / "base/en/src/skills.tex"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert combined_hash(input_hashes(sample_dir, p)) == before


def test_editing_one_preset_does_not_stale_others(sample_dir: Path) -> None:
    presets = load_presets(sample_dir).presets
    for p in presets:
        write_manifest(sample_dir, p, "anthropic", "m", 0.1, {}, "0.1.0")
    yml = sample_dir / "presets.yml"
    yml.write_text(yml.read_text(encoding="utf-8").replace(
        "Backend roles:", "Backend and API roles:"), encoding="utf-8")
    fresh = load_presets(sample_dir).presets
    assert [status(sample_dir, p) for p in fresh] == ["up to date", "up to date", "outdated"]
