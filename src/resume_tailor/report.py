"""`match-report.md`: written in English, for the owner."""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog
from .checks import KeywordReport
from .models import Analysis, Tailoring
from .providers.base import LLMResponse


@dataclass
class ReportData:
    title: str
    kind: str  # application | preset
    generated: str
    analysis: Analysis
    tailoring: Tailoring
    keywords: KeywordReport | None
    responses: list[LLMResponse]
    fit_log: list[str]
    empty: dict[str, float]
    warnings: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    prompt_version: str = "v1"


def _bullets(items: list[str], empty: str = "_none_") -> str:
    return "\n".join(f"- {x}" for x in items) if items else empty


def render_report(cat: Catalog, d: ReportData) -> str:
    total = round(sum(r.cost_usd for r in d.responses), 4)
    final = d.responses[-1] if d.responses else None
    out = [f"# {d.title}", ""]
    meta = f"Generated {d.generated}"
    if final:
        meta += f" · {final.provider} ({final.model}) · cost ${total:.4f}"
    out += [meta, ""]

    if d.notices:
        out += ["> **Notices**", *[f"> - {n}" for n in d.notices], ""]

    if d.keywords is not None:
        k = d.keywords
        pct = k.match_pct
        n_total = len(k.present) + len(k.missing_with_evidence) + len(k.gaps)
        out += [f"## Keyword match: {pct if pct is not None else '–'}% "
                f"({len(k.present)} of {n_total}, English PDF)", ""]
        out += ["### Present on the page", _bullets(k.present), ""]
        out += ["### You have evidence, but it was left out (space or relevance)",
                _bullets(k.missing_with_evidence), ""]
        gaps = list(dict.fromkeys([*k.gaps, *d.tailoring.gaps]))
        out += ["### Gaps: no evidence in your inventory", _bullets(gaps), ""]
        a = d.analysis
        out += ["### Posting requirements", "**Must have:** " + (", ".join(a.must_have) or "–"),
                "", "**Nice to have:** " + (", ".join(a.nice_to_have) or "–"), ""]
    else:
        out += ["## Preset build", "", f"Position: {d.analysis.position}", ""]
        if d.tailoring.gaps:
            out += ["### Gaps", _bullets(d.tailoring.gaps), ""]

    out += ["## What changed", _bullets(d.tailoring.changes), ""]
    sel = [p.id for p in d.tailoring.projects]
    out += ["## Selection", "Projects (in order): "
            + ", ".join(f"{p} {cat.entries[p].inv.title}" for p in sel), ""]

    out += ["## One-page fit",
            f"Empty space at the bottom: EN {d.empty.get('en', 0):.0%}, "
            f"TR {d.empty.get('tr', 0):.0%}.", _bullets(d.fit_log, "_no changes needed_"), ""]

    dnc = []
    for eid in [*[e.id for e in d.tailoring.experience], *sel]:
        for line in cat.entries[eid].inv.do_not_claim:
            dnc.append(f"{eid}: {line}")
    out += ["## Check by eye",
            "The fact guard verified numbers, ids, statuses, skills, stack items and known "
            "technology names. These inventory notes are prose and cannot be checked by "
            "code. Make sure the PDFs respect them:", _bullets(dnc), ""]
    if d.warnings:
        out += ["### Warnings", _bullets(d.warnings), ""]

    out += ["---", "", "| Call | Provider | Model | In | Out | Cache write | Cache read | Cost |",
            "|---|---|---|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(d.responses, 1):
        u = r.usage
        out.append(f"| {i} | {r.provider} | {r.model} | {u.input_tokens} | {u.output_tokens} | "
                   f"{u.cache_write_tokens} | {u.cache_read_tokens} | ${r.cost_usd:.4f} |")
    out += ["", f"Total cost: **${total:.4f}** · prompts {d.prompt_version}", ""]
    return "\n".join(out)
