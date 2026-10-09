"""Text helpers shared by the guard, the keyword matcher and redaction.

Everything that *compares* text goes through `fold()`. Python's `str.lower()` maps the
Turkish dotted capital `İ` to `i̇` (i + combining dot) and leaves dotless `ı` alone, so
"İSTANBUL", "Istanbul" and "istanbul" would never match. We fold all four Turkish i's to
plain `i` instead: matching should be lenient across languages, never stricter.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_I_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def fold(text: str) -> str:
    """Case- and dot-insensitive form for matching (not for display)."""
    text = unicodedata.normalize("NFC", text).translate(_I_FOLD)
    text = text.casefold()
    # Hyphen/space/slash variants of the same term ("scikit-learn", "scikit learn").
    text = re.sub(r"[‐-―\-_/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tr_lower(text: str) -> str:
    """Turkish-correct lowercase for display (İ→i, I→ı)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def contains_term(haystack_folded: str, term: str) -> bool:
    """Whole-term match on folded text. Handles terms like C++, C#, .NET, Node.js."""
    t = fold(term)
    if not t:
        return False
    pattern = r"(?<![\w])" + re.escape(t) + r"(?![\w])"
    # A term ending in a symbol (C++, C#) cannot use \w lookahead meaningfully, but the
    # pattern above still works: '+' is not \w, so the boundary is checked on what follows.
    return re.search(pattern, haystack_folded) is not None


# ---------------------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------------------

_EN_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "thousand": 1000, "dozen": 12, "dozens": 12, "single": 1, "once": 1, "twice": 2,
    "double": 2, "triple": 3,
}
# "bir" (one) is left out on purpose: it is also the Turkish indefinite article ("a").
# "one" is left out for the same reason in English ("one-time", "one of").
_TR_WORDS = {
    "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8,
    "dokuz": 9, "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "yüz": 100,
    "bin": 1000, "çift": 2,
}

# A number not glued to a preceding letter ("OAuth2", "B2", "H100" are names, not counts),
# with optional thousands separators and a decimal part in either convention.
_NUM_RE = re.compile(r"(?<![A-Za-zÀ-ɏ])(\d+(?:[.,]\d+)*)")


def _canonical(raw: str) -> str | None:
    """'10.000' / '10,000' → '10000'; '0,85' / '0.85' → '0.85'; '1.0' → '1'."""
    parts = re.split(r"[.,]", raw)
    if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3:
        # Thousands grouping in either locale: 1,000 (EN) or 1.000 (TR).
        value = "".join(parts)
    elif len(parts) == 2:
        value = f"{parts[0]}.{parts[1]}"
    elif len(parts) == 1:
        value = parts[0]
    else:
        value = "".join(parts)
    try:
        d = Decimal(value).normalize()
    except InvalidOperation:
        return None
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def extract_numbers(text: str) -> set[str]:
    """Every quantity a reader would see in `text`, in canonical form.

    Spelled-out numbers count: an LLM writing "three services" where the source says
    "two" is exactly the error the fact guard exists to catch.
    """
    found: set[str] = set()
    for m in _NUM_RE.finditer(text):
        c = _canonical(m.group(1))
        if c is not None:
            found.add(c)
    words = re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", text))
    for w in words:
        lw = tr_lower(w)
        if lw in _TR_WORDS:
            found.add(str(_TR_WORDS[lw]))
        elif w.lower() in _EN_WORDS:
            found.add(str(_EN_WORDS[w.lower()]))
    return found


def slug_ascii(text: str) -> str:
    """'Sr. iOS Developer' → 'Sr_iOS_Developer'; 'Veri Bilimci' → 'Veri_Bilimci'."""
    table = str.maketrans({
        "ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G",
        "ü": "u", "Ü": "U", "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
    })
    text = text.translate(table)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_")
