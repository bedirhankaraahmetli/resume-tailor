"""ATS text check and keyword coverage.

The ATS check reads the PDF the way a parser does (pypdf text extraction) and fails on
what makes text unreadable to one: ligature glyphs (U+FB00–FB06) instead of letters, and
accents extracted as separate characters ("g˘" instead of "ğ").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Analysis
from .text import contains_term, fold

_DETACHED = "¨˘˙¸˛ˇ˝`´"


def _squash(text: str) -> str:
    return "".join(ch for ch in fold(text) if ch.isalnum() or ch in "+#")


def on_page(page_folded: str, page_squashed: str, term: str) -> bool:
    """Is `term` in the PDF text? pypdf splits words at kerning pairs in some fonts
    ("PyT orch", "T urkish"), so a whole-word match is tried first and a space-insensitive
    one second (only for terms long enough not to match by accident)."""
    if contains_term(page_folded, term):
        return True
    sq = _squash(term)
    return len(sq) >= 4 and sq in page_squashed


@dataclass
class AtsResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ats_check(text: str, *, names: list[str], email: str, lang: str,
              must_have: list[list[str]] | None = None) -> AtsResult:
    """`must_have`: for each must-have keyword the owner has evidence for, its accepted
    forms (term + synonyms, so the Turkish PDF may use the Turkish form)."""
    r = AtsResult()
    lig = sorted({f"U+{ord(c):04X}" for c in text if 0xFB00 <= ord(c) <= 0xFB06})
    if lig:
        r.errors.append(f"{lang}: ligature characters in text layer ({', '.join(lig)})")
    det = sorted({c for c in text if c in _DETACHED})
    if det:
        r.errors.append(f"{lang}: detached accent characters ({' '.join(det)})")
    ft, fs = fold(text), _squash(text)
    if not any(fold(n) in ft or _squash(n) in fs for n in names):
        r.errors.append(f"{lang}: owner name not found in PDF text")
    if fold(email) not in ft.replace(" ", ""):
        r.errors.append(f"{lang}: email not found in PDF text")
    for forms in must_have or []:
        if forms and not any(on_page(ft, fs, f) for f in forms):
            r.warnings.append(f"{lang}: must-have keyword '{forms[0]}' (you have evidence) "
                              "is not in the PDF")
    return r


@dataclass
class KeywordReport:
    present: list[str]
    missing_with_evidence: list[str]
    gaps: list[str]
    must_have_with_evidence: list[list[str]]  # accepted forms per keyword

    @property
    def match_pct(self) -> int | None:
        total = len(self.present) + len(self.missing_with_evidence) + len(self.gaps)
        return round(100 * len(self.present) / total) if total else None


def keyword_report(analysis: Analysis, en_text: str, inventory_text: str) -> KeywordReport:
    """match % = keywords found in the EN text / all keywords (PROMPT.md §5.7)."""
    ft, fs, fi = fold(en_text), _squash(en_text), fold(inventory_text)
    present: list[str] = []
    missing: list[str] = []
    gaps: list[str] = []
    must: list[list[str]] = []
    for kw in analysis.keywords:
        forms = [kw.term, *kw.synonyms]
        if any(on_page(ft, fs, f) for f in forms):
            present.append(kw.term)
        elif any(contains_term(fi, f) for f in forms):
            missing.append(kw.term)
        else:
            gaps.append(kw.term)
            continue
        if kw.importance == "must":
            must.append(forms)
    return KeywordReport(present, missing, gaps, must)
