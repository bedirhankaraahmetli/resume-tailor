"""Redaction: what may approach an LLM provider.

Contact details are never tailored, so no provider ever needs them. Before any call:
the inventory's Contact section and `heading.tex` are never included; the owner's name
becomes CANDIDATE; emails, phone numbers and *all* URLs are scrubbed (the owner's GitHub
username is their name, so project links identify them — the renderer re-attaches links
from the inventory). Then `assert_clean` checks the final serialized request body and
aborts if any configured contact string survived: fail closed.
"""

from __future__ import annotations

import re

from .text import fold

PLACEHOLDER = "CANDIDATE"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_BARE_URL = re.compile(
    r"\b[\w-]+(\.[\w-]+)*\.(com|org|dev|app|ai|co|me|tr|edu|info)\b(/[^\s,;)]*)?",
    re.IGNORECASE,
)
# 9+ digits with the separators phone numbers use; "10,000" and dates never match.
_PHONE = re.compile(r"(?<![\w.,])\+?\d[\d\s().-]{7,}\d(?![\w])")


class RedactionError(RuntimeError):
    pass


def _name_pattern(names: list[str]) -> re.Pattern[str]:
    parts: set[str] = set()
    for n in names:
        parts.add(n)
        parts.update(p for p in n.split() if len(p) > 2)
    alts = sorted(parts, key=len, reverse=True)
    # Turkish attaches suffixes with an apostrophe: Yılmaz'ın, Deniz'in.
    body = "|".join(_fuzzy_i(re.escape(a)) for a in alts)
    return re.compile(r"(?<!\w)(?:" + body + r")(?:['’]\w+)?(?!\w)", re.IGNORECASE)


def _fuzzy_i(escaped: str) -> str:
    # Match any of the four Turkish i's wherever the name has one.
    return re.sub(r"[iIıİ]", "[iIıİ]", escaped)


def redact(text: str, names: list[str], contact_strings: list[str] | None = None) -> str:
    # Configured contact strings first (address, usernames): exact, case-insensitive.
    for s in sorted(contact_strings or [], key=len, reverse=True):
        if s.strip():
            text = re.sub(_fuzzy_i(re.escape(s)), "[redacted]", text, flags=re.IGNORECASE)
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[link]", text)
    text = _BARE_URL.sub("[link]", text)
    text = _PHONE.sub("[phone]", text)
    return _name_pattern(names).sub(PLACEHOLDER, text)


def assert_clean(payload: str, names: list[str], contact_strings: list[str]) -> None:
    """Abort if the outgoing payload still contains anything personal."""
    folded = fold(payload)
    # Digits of each phone-like run separately: joining all digits in the payload would
    # "find" a phone number assembled from unrelated numbers.
    runs = [re.sub(r"\D", "", m) for m in re.findall(r"\+?\d[\d\s().+-]*\d", payload)]
    leaks = []
    for s in [*names, *contact_strings]:
        if not s.strip():
            continue
        digits = re.sub(r"\D", "", s)
        if (len(digits) >= 9 and any(digits in r for r in runs)) or fold(s) in folded:
            leaks.append(s)
    if leaks:
        # Never echo the strings themselves: this message can reach CI logs.
        raise RedactionError(
            f"refusing to call the LLM: {len(leaks)} personal string(s) survived redaction"
        )
