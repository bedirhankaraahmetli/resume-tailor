"""Parse `career-inventory.md` into an `Inventory`.

The format is the owner's hand-written markdown (see sample-data/career-inventory.md):

    ## 3. Experience
    ### Employer, Title          → id 3.1, 3.2, … in order
    ## 4. Projects
    ### 4.1 Name: Subtitle       → id 4.1
    - Key: value                 (continuation lines are indented)
    - Bullets (…):
      - bullet
    - Do not claim: …

A sentence that says "do not" / "never" is *negative*: its numbers are forbidden even
though they appear in the file (e.g. "Do **not** use 99%").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import InvCertificate, Inventory, InvEntry

_NEG_RE = re.compile(r"\b(do\s+(\*\*)?not(\*\*)?|don't|never|must not)\b", re.IGNORECASE)
_STATUS_RE = re.compile(r"`(shipped|in-review|complete|in-progress|planned)`")


class InventoryError(ValueError):
    pass


@dataclass
class _Item:
    key: str | None
    value: str
    subs: list[str] = field(default_factory=list)


def _split_sections(text: str, level: int) -> list[tuple[str, str]]:
    """[(heading, body)] for headings of exactly `level` #'s."""
    marker = "#" * level + " "
    out: list[tuple[str, str]] = []
    cur_head: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith(marker) and not line.startswith(marker + "#"):
            if cur_head is not None:
                out.append((cur_head, "\n".join(buf)))
            cur_head, buf = line[len(marker) :].strip(), []
        elif cur_head is not None:
            if re.match(rf"^#{{1,{level - 1}}} ", line):
                out.append((cur_head, "\n".join(buf)))
                cur_head, buf = None, []
            else:
                buf.append(line)
    if cur_head is not None:
        out.append((cur_head, "\n".join(buf)))
    return out


def _items(body: str) -> list[_Item]:
    items: list[_Item] = []
    for line in body.splitlines():
        if not line.strip() or line.strip() == "---":
            continue
        if line.startswith("- "):
            content = line[2:].strip()
            m = re.match(r"^([A-Za-z][^:]{0,40}?):\s*(.*)$", content)
            if m:
                items.append(_Item(m.group(1).strip(), m.group(2).strip()))
            else:
                items.append(_Item(None, content))
        elif re.match(r"^\s+- ", line) and items:
            items[-1].subs.append(line.strip()[2:].strip())
        elif line.startswith((" ", "\t")) and items:
            items[-1].value = (items[-1].value + " " + line.strip()).strip()
    return items


def _clean_md(s: str) -> str:
    s = re.sub(r"\*\(([^)]*)\)\*", "", s)  # *(editorial notes)*
    s = s.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def _sentences(s: str) -> list[str]:
    return [p for p in re.split(r"(?<=[.;])\s+|\n", s) if p.strip()]


def split_terms(s: str) -> list[str]:
    """'Swift (AlarmKit, App Intents), Drift + SQLCipher, Java 21' → every usable name.

    Versioned names also yield their unversioned form ('Java 21' → 'Java'), because the
    base resume and postings use both and both are true.
    """
    s = _clean_md(s)
    parts: list[str] = []
    depth, cur = 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)

    out: list[str] = []

    def add(name: str) -> None:
        name = name.strip().strip(".").strip()
        # Language codes inside "(EN + TR)" describe a feature, not a technology.
        if not name or len(name) > 40 or name in {"EN", "TR"}:
            return
        if name not in out:
            out.append(name)
        m = re.match(r"^(.*\D)\s+\d+(\.\d+)?$", name)
        if m and m.group(1).strip() not in out:
            out.append(m.group(1).strip())

    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r"^(.*?)\s*\((.*)\)\s*$", p)
        outer, inner = (m.group(1), m.group(2)) if m else (p, "")
        for piece in re.split(r"\s+\+\s+|\s+/\s+", outer):
            add(piece)
        for piece in re.split(r",|\s+\+\s+|/", inner):
            add(piece)
    return out


def _parse_entry(entry_id: str, kind: str, title: str, body: str) -> InvEntry:
    e = InvEntry(id=entry_id, kind=kind, title=_clean_md(title))  # type: ignore[arg-type]
    positive: list[str] = [e.title]
    negative: list[str] = []
    for it in _items(body):
        key = (it.key or "").lower()
        value = _clean_md(it.value)
        if key.startswith("do not claim") or key.startswith("not evidenced"):
            e.do_not_claim.append(value)
            negative.append(value)
            continue
        if key == "status":
            m = _STATUS_RE.search(it.value)
            e.status = m.group(1) if m else None
        if key in ("resume use", "allow in-progress", "allow on resume"):
            e.allow_in_progress = bool(re.search(r"\b(allowed|yes|true)\b", value, re.I))
        if key == "link":
            m = re.search(r"https?://\S+", it.value)
            e.link = m.group(0).rstrip(").,") if m else None
        if key.startswith("stack"):
            if key in ("stack", "stack (own work)"):
                e.stack.extend(t for t in split_terms(it.value) if t not in e.stack)
            # Stack lines are not citable numbers: "Dart 3" must not let a bullet claim
            # "3 apps". Versioned names in bullets are handled by the guard instead.
            continue
        if key.startswith("bullets"):
            e.bullets.extend(_clean_md(b) for b in it.subs)
            positive.extend(_clean_md(b) for b in it.subs)
            continue
        for sent in _sentences(value):
            (negative if _NEG_RE.search(sent) else positive).append(sent)
        for sub in it.subs:
            (negative if _NEG_RE.search(sub) else positive).append(_clean_md(sub))
    e.positive_text = "\n".join(positive)
    e.negative_text = "\n".join(negative)
    return e


def _table_rows(body: str) -> list[list[str]]:
    rows = []
    for line in body.splitlines():
        if line.strip().startswith("|") and not re.match(r"^\s*\|[\s|:-]+\|\s*$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]  # drop the header row


def parse_inventory(text: str) -> Inventory:
    text = text.replace("\r\n", "\n")
    sections = {_num(h): (h, b) for h, b in _split_sections(text, 2)}
    for need in ("1", "2", "3", "4", "5", "6"):
        if need not in sections:
            raise InventoryError(f"inventory is missing section '## {need}. …'")

    contact_lines = [ln[2:].strip() for ln in sections["1"][1].splitlines() if ln.startswith("- ")]

    edu_body = sections["2"][1]
    courses: list[str] = []
    for it in _items(edu_body):
        if it.key is None and it.value.lower().startswith("full course list"):
            raw = it.value.split(":", 1)[1] if ":" in it.value else ""
            for c in raw.split(","):
                c = re.sub(r"\([^)]*\)", "", c).strip().strip(".").strip()
                if c:
                    courses.append(c)

    experience = [
        _parse_entry(f"3.{i}", "experience", head, body)
        for i, (head, body) in enumerate(_split_sections(sections["3"][1], 3), start=1)
    ]
    projects: list[InvEntry] = []
    for head, body in _split_sections(sections["4"][1], 3):
        m = re.match(r"^(4\.\d+)\s+(.*)$", head)
        if not m:
            raise InventoryError(f"project heading must start with '4.n': {head!r}")
        projects.append(_parse_entry(m.group(1), "project", m.group(2), body))

    certificates: list[InvCertificate] = []
    for i, row in enumerate(_table_rows(sections["5"][1]), start=1):
        if len(row) < 5:
            continue
        dates = [d.strip() for d in row[2].split("/")]
        link = re.search(r"https?://\S+", row[4])
        certificates.append(InvCertificate(
            id=f"5.{i}", name=row[0], issuer=row[1], date_en=dates[0],
            date_tr=dates[-1], link=link.group(0) if link else "",
        ))

    skills_body = sections["6"][1]
    skills: list[str] = []
    for row in _table_rows(skills_body):
        for t in split_terms(row[0]):
            if t not in skills:
                skills.append(t)
    never: list[str] = []
    m = re.search(r"\*\*Not evidenced, never claim:\*\*(.*?)(?:\n\s*\n|\Z)", skills_body, re.S)
    if m:
        for t in re.split(r",|/", m.group(1).replace("\n", " ")):
            t = t.strip().strip(".").strip()
            if t:
                never.append(t)

    return Inventory(
        raw=text, contact_lines=contact_lines, education_text=edu_body, courses=courses,
        experience=experience, projects=projects, certificates=certificates, skills=skills,
        skills_text=skills_body, never_claim=never,
    )


def _num(heading: str) -> str:
    m = re.match(r"^(\d+)\.", heading)
    return m.group(1) if m else heading


def strip_contact_section(text: str) -> str:
    """The inventory minus `## 1. Contact` — the only form that may approach an LLM."""
    text = text.replace("\r\n", "\n")
    return re.sub(r"(?ms)^## 1\..*?(?=^## 2\.)", "", text)
