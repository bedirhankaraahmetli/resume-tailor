"""Cover letters: the model writes the body; everything else is fixed here.

The letter is built on the base resume's own preamble (same document class, fonts,
margins and packages) and its `src/heading.tex`, so the letterhead and contact details
are the resume's, copied verbatim (T2). Nothing in the base is modified: the preamble is
read from `resume.tex` and the letter is compiled as a separate `letter.tex`.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from .latex import escape
from .models import CoverLetter

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
             "Eylül", "Ekim", "Kasım", "Aralık"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


class LetterError(RuntimeError):
    pass


def letter_date(d: date, lang: str) -> str:
    if lang == "tr":
        return f"{d.day} {TR_MONTHS[d.month - 1]} {d.year}"
    return f"{EN_MONTHS[d.month - 1]} {d.day}, {d.year}"


def preamble(resume_tex: str) -> str:
    """Everything before `\\begin{document}` in the base resume, unchanged."""
    text = resume_tex.replace("\r\n", "\n")
    cut = text.find("\\begin{document}")
    if cut < 0:
        raise LetterError("the base resume.tex has no \\begin{document}")
    return text[:cut]


def _join(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" ve " if lang == "tr" else " and ") + items[-1]


def learning_sentence(letter: CoverLetter, lang: str) -> str | None:
    """The one sentence that may name a missing skill, written here so its wording can
    only ever admit the gap ("not yet, keen to learn"), never claim it."""
    names = [(i.tr if lang == "tr" else i.en).strip() for i in letter.learning]
    names = [n for n in names if n]
    if not names:
        return None
    what = _join(names, lang)
    if lang == "tr":
        them = "bunları" if len(names) > 1 else "bunu"
        return f"{what} ile henüz çalışmadım, ancak {them} hızlıca öğrenmeye hazırım."
    them = "them" if len(names) > 1 else "it"
    return f"I have not worked with {what} yet, and I am keen to learn {them} quickly."


def render_letter(resume_tex: str, letter: CoverLetter, lang: str, *, company: str | None,
                  position: str, signer: str, today: date) -> str:
    """The complete `letter.tex`. Deterministic: the same inputs give the same text."""
    paragraphs = [(p.en if lang == "en" else p.tr) or "" for p in letter.paragraphs]
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if not paragraphs:
        raise LetterError(f"the letter has no {lang} text")
    learning = learning_sentence(letter, lang)
    if learning:
        # Before the closing paragraph, which thanks the reader and should come last.
        paragraphs.insert(max(len(paragraphs) - 1, 1), learning)
    if lang == "tr":
        greeting = f"Sayın {company} İşe Alım Ekibi," if company else "Sayın Yetkili,"
        subject = f"{position} pozisyonu için başvuru"
        closing = "Saygılarımla,"
    else:
        greeting = f"Dear {company} Hiring Team," if company else "Dear Hiring Team,"
        subject = f"Application for {position}"
        closing = "Sincerely,"
    body = "\n\n".join(escape(p) for p in paragraphs)
    return (
        preamble(resume_tex)
        + "\\begin{document}\n"
        + "\\input{src/heading}\n"
        # The resume is \raggedright with no paragraph spacing; a letter needs a gap
        # between paragraphs. This changes the letter only, never the resume.
        + "\\setlength{\\parindent}{0pt}\n\\setlength{\\parskip}{8pt}\n"
        + "\\vspace{14pt}\n"
        + f"\\hfill {escape(letter_date(today, lang))}\n\n"
        + f"\\textbf{{{escape(subject)}}}\n\n"
        + f"{escape(greeting)}\n\n"
        + body + "\n\n"
        + f"{escape(closing)}\n\n"
        + f"{escape(signer)}\n"
        + "\\end{document}\n"
    )


def prepare_letter(base_dir: Path, tex: str, build_dir: Path) -> None:
    """The heading and macros the letter inputs, copied verbatim, plus `letter.tex`."""
    (build_dir / "src").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_dir / "custom-commands.tex", build_dir / "custom-commands.tex")
    shutil.copyfile(base_dir / "src" / "heading.tex", build_dir / "src" / "heading.tex")
    (build_dir / "letter.tex").write_text(tex, encoding="utf-8", newline="\n")
