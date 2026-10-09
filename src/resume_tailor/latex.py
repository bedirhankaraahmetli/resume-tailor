"""LaTeX escaping (text → .tex) and a small reader for the base resume's macros.

The LLM never writes LaTeX. Every string it produces goes through `escape()` before it
reaches a .tex file, so a posting that says "use 100% of $budget & C#" cannot break the
compile or inject a command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Characters the pdfLaTeX + T1 + inputenc(utf8) setup of the base cannot typeset directly.
# Each mapping keeps the PDF text layer readable for ATS parsers.
_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "–": "--",
    "—": "---",
    "×": r"$\times$",
    "→": r"$\rightarrow$",
    "←": r"$\leftarrow$",
    "≥": r"$\geq$",
    "≤": r"$\leq$",
    "±": r"$\pm$",
    # The Lato T1 font has no Turkish lira glyph; inputenc would abort on it.
    "₺": "TL ",
    " ": "~",
}

# Latin-1 + Latin Extended-A covers English, Turkish and the usual typographic marks that
# inputenc(utf8) + T1 knows. Anything else is reported rather than silently mis-rendered.
_SAFE = re.compile(r"[\x20-\x7E¡-ÿĀ-ſ‘’“”…•]")


class UnsupportedCharacter(ValueError):
    pass


def escape(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in _SPECIAL:
            out.append(_SPECIAL[ch])
        elif ch in "\n\t\r":
            out.append(" ")
        elif _SAFE.fullmatch(ch):
            out.append(ch)
        else:
            raise UnsupportedCharacter(f"cannot typeset {ch!r} (U+{ord(ch):04X}) with pdfLaTeX")
    return "".join(out)


# ---------------------------------------------------------------------------------------
# Reading the base files
# ---------------------------------------------------------------------------------------


def read_group(s: str, i: int) -> tuple[str, int]:
    """Return the content of the brace group starting at or after `i`, and the index after it."""
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s) or s[i] != "{":
        raise ValueError(f"expected '{{' at {i}: {s[i:i + 30]!r}")
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
        j += 1
    raise ValueError("unbalanced braces")


@dataclass(frozen=True)
class MacroCall:
    start: int
    end: int
    args: list[str]


def find_calls(s: str, name: str, nargs: int) -> list[MacroCall]:
    calls: list[MacroCall] = []
    for m in re.finditer(r"\\" + re.escape(name) + r"(?![A-Za-z])", s):
        if s[: m.start()].rsplit("\n", 1)[-1].lstrip().startswith("%"):
            continue  # commented out
        i = m.end()
        args: list[str] = []
        for _ in range(nargs):
            arg, i = read_group(s, i)
            args.append(arg)
        calls.append(MacroCall(m.start(), i, args))
    return calls


def to_text(tex: str) -> str:
    """Plain text of a LaTeX fragment from the base resume (the inverse of `escape`)."""
    s = tex
    # \href{url}{label} → label
    while True:
        m = re.search(r"\\href(?![A-Za-z])", s)
        if not m:
            break
        _url, i = read_group(s, m.end())
        label, j = read_group(s, i)
        s = s[: m.start()] + label + s[j:]
    for cmd in ("textbf", "emph", "textit", "underline", "texttt", "small", "large"):
        s = re.sub(r"\\" + cmd + r"(?![A-Za-z])\s*", "", s)
    s = s.replace("$|$", "|").replace(r"$\times$", "×").replace(r"$\rightarrow$", "→")
    s = s.replace("---", "—").replace("--", "–")
    for k, v in ((r"\&", "&"), (r"\%", "%"), (r"\$", "$"), (r"\#", "#"), (r"\_", "_"),
                 (r"\{", "{"), (r"\}", "}"), (r"\textasciitilde{}", "~"), ("~", " ")):
        s = s.replace(k, v)
    s = re.sub(r"\\\\(\[[^\]]*\])?", " ", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()
