# Resume Tailor — Engineering Guide

> This folder sits under `Desktop/`, whose own `CLAUDE.md` belongs to **DoseClock**, a
> different project. None of it applies here. Only this file governs Resume Tailor.

The spec is [PROMPT.md](PROMPT.md). The plan, the schemas and the open decisions are in
[docs/PLAN.md](docs/PLAN.md). If this file and PLAN.md disagree, this file wins; fix the
other one.

---

## 1. What this is

A personal tool. It takes a job posting and produces one-page EN + TR PDF resumes, tailored
to that posting, from the owner's existing LaTeX resume. It also produces a match report and
a log row. A Python core runs as a CLI and in GitHub Actions; a static web app on GitHub
Pages triggers it from a PC or an iPhone.

There are two repos:
- **`resume-tailor` (public, this one):** the code, a reusable workflow, the web app, and
  sample data about a **fictional** person.
- **`resume-data` (private):** the real resumes, the career inventory, config, requests,
  outputs, logs and secrets.

**Where things are.**
- **The owner's real data** is the sibling folder `../resume-data`, which becomes the
  private repo. Never copy anything from it into this repo.
- **The pipeline** is `pipeline.py`: analyze → tailor → `guard.check` → `render` →
  `fit` (pdfLaTeX) → `checks` → outputs.
- **`catalog.py`** joins the inventory, both bases and the config by id. The renderer and
  the guard read only the catalog.
- **GitHub Actions** runs `.github/workflows/tailor.yml` (reusable), called from the data
  repo's workflow that `tailor init-data-repo` writes. It runs the stages as separate steps
  through `jobs.py` (`tailor request start|analyze|tailor|compile|finish`). The step names
  are a contract with the web app. Design notes are in PLAN.md §0, "Phase 2 notes".
- **`tailor check --data-dir ../resume-data`** must pass after any change to the base
  parser or renderer: it runs the identity round-trip on the real data.
- **Tests:** run `RT_DATA_DIR=../resume-data pytest` to include the real-data tests.

---

## 2. Principles (product law)

If a technical decision conflicts with one of these, stop and raise it. Never quietly
compromise.

| # | Principle |
|---|---|
| T1 | **Truth beats match score.** Nothing appears on a resume that is not in `career-inventory.md` or the base resumes. A real gap goes in the report, never on the page. |
| T2 | **The layout is fixed.** Same template, macros, section order and fonts. Only the content is selected, reordered and rephrased. Contact info is copied verbatim. |
| T3 | **Rules are enforced in code, not only in prompts.** Structured JSON → Pydantic → fact guard → one repair round → fail clearly. |
| T4 | **No personal data leaves toward an LLM.** Redact, then check the final serialized payload against the owner's contact strings, and abort if any survive. |
| T5 | **No personal data or secrets in the public repo.** Ever. Sample data is fictional. |
| T6 | **Money is visible and capped.** Every call's cost is computed from `usage` and recorded. The budget guard and the prepaid balance cap spend. Running out degrades to a fallback provider, never to a broken tool. |
| T7 | **No paid infrastructure.** GitHub Actions, Pages and the API are the only moving parts. |
| T8 | **EN and TR carry the same selection and order.** Only the language differs, and fitting is joint. |

---

## 3. Never do

- Never invent or inflate a project, role, date, metric, count, skill, technology,
  certificate or employer. Never use a `planned` item. Never use a "Do not claim" item.
- Never add a section (no summary, no objective). Never edit contact info, education facts,
  dates, employer names or certificate names. Certificate names stay in their official
  English form in both languages.
- Never modify `resume.tex` or `custom-commands.tex`. Never compile with XeLaTeX, LuaLaTeX
  or Tectonic. pdfLaTeX only.
- Never let the LLM write raw LaTeX. It returns JSON; Python escapes everything
  (`& % $ # _ { } ~ ^ \`) and renders with the documented macros.
- Never shrink fonts, margins or spacing to make a page fit. Drop content, or fail.
- Never send `heading.tex`, inventory §1 (Contact), the owner's name, phone, email or
  personal URLs to any provider. Never send URLs at all; the renderer re-attaches links.
- Never let CI or the test suite call a live LLM. Tests block sockets. The single live smoke
  test needs `RT_LIVE_SMOKE=1`.
- Never run a command that spends API credits without first telling the owner the estimated
  cost. During development, use `--provider claude-code` or the cheapest model.
- Never hard-code model ids or prices. They live in `config.yml`, with prices dated.
- Never commit `.env`, real resumes, the real inventory, real outputs or anything from
  `resume-data` into this repo.
- Never print secrets, posting text or resume content in Actions logs beyond what's needed.
- Never load a third-party script at runtime in the web app. Never add analytics. The PAT is
  sent only to `api.github.com`.
- Never retry a billing error (HTTP 402 `billing_error`). Fall back instead.

---

## 4. Truthfulness rules (enforced by the fact guard)

1. Every bullet cites the inventory section ids it came from (`"sources": ["4.1"]`).
2. Every number, percentage and count in `en` **and** `tr` appears in the cited sources'
   text, after normalisation (`%15` = `15%`, `1.000` = `1,000`, `0,85` = `0.85`). Spelled-out
   numbers (`three`, `üç`) count as numbers.
3. Every skill and stack item is in the inventory (canonical names plus an alias table).
   Each project's stack is a subset of that project's own inventory stack, at most 7 items.
4. Every project id exists. Allowed statuses: `shipped`, `in-review`, `complete`.
   `in-progress` only if its entry permits it, and then it is labelled. `planned` never.
5. No "Do not claim" term appears (Turkish-aware casefold, alias-aware).
6. Experience is never dropped. At least 3 projects when available.
7. Facts Python can own, it owns. Dates, employers, titles, URLs, certificate names and
   education entries come from the inventory by id, never from LLM text.

A violation triggers one repair round with the error list. A second failure fails the run,
and every violation is listed in the report and in `results/<id>.json`.

**Turkish style:** active voice, first person, past tense ("geliştirdim", "kurdum"), never
passive ("geliştirildi"). The TR base resume is the reference for tone and terms.

---

## 5. Stack

| Concern | Choice |
|---|---|
| Core | Python ≥ 3.12, `src/` layout, package `resume_tailor`, console script `tailor` |
| CLI | `argparse` (no framework) |
| Models | Pydantic v2. The JSON Schema sent to providers is generated from these models, so there is one source |
| LLM: default | `anthropic` SDK. `messages.parse()` + `output_config.format` (structured outputs; the current Sonnet **rejects forced tool use**), `cache_control` on the static block |
| LLM: fallback 1 | Claude Code headless (`claude -p`, JSON). Runs in an empty temp dir, with no tools and its own system prompt |
| LLM: fallback 2 | `google-genai` with a response schema, on the free tier |
| PDF | `pdflatex` (TinyTeX in CI and locally). `pypdf` for page count, text extraction and fill measurement |
| Config | `pyyaml` |
| Web | Vite + TypeScript, no framework, `pdfjs-dist` bundled |
| Dev | `pytest`, `ruff`, `mypy` |

**Dependency rule:** every runtime dependency must earn its place. This tool promises
privacy, and each package is a supply-chain risk. Prefer 50 lines of our own over a new
transitive tree. Justify additions in the PR or commit message.

---

## 6. Conventions

- **Layering:**
  - `models/` and `guard/` are pure: no I/O, no network.
  - `providers/` are the only modules that touch the network.
  - `pipeline/` orchestrates the rest.
- **Errors:** expected failures (fact-guard violations, page overflow, no provider
  available) are typed results with actionable messages. Exception strings never reach the
  report or the web app raw.
- **Determinism:** fitting, rendering, naming and hashing are deterministic. The same JSON in
  gives the same `.tex` out.
- **Text handling:**
  - Turkish-aware casefolding everywhere text is compared (`İ/i`, `I/ı`). Never use
    `str.lower()` for matching.
  - Normalise CRLF → LF before hashing.
- **Naming:** follow PROMPT.md §5 "Naming" exactly. The position is verbatim from the
  posting; a manual position wins. Folder: Windows-invalid characters removed, `(2)` on
  collision. Slug: ASCII-transliterated.
- **Prompts:** versioned files in `prompts/` (`tailor.v1.md`), shared by all providers.
  Change a prompt by adding a new version.
- **Comments:** explain *why*. Name the API or OS behaviour behind any workaround.
- **Cost:** every LLM call writes a row to the data repo's `usage.csv`, including calls from
  failed runs and preset builds. The budget guard sums this month's rows.

---

## 7. Testing

- **Unit:** inventory parser (real format), naming, escaping, fact guard (one test per rule
  plus Turkish number formats), fit loop (with a fake compiler), keyword matching, and
  redaction (with the real config strings, read at test time, never copied here).
- **Golden:** the sample JSON renders to the expected `.tex`. The **identity round-trip** (base
  content in, base `.tex` out) proves the layout is untouched.
- **Integration:** compile, one page, ATS text check. Skipped when `pdflatex` is missing.
- **LLM:** recorded fixtures only. Record each once from a real run, then replay it.
- **CI:** ruff, mypy, pytest, the privacy scan and gitleaks, on every push.

---

## 8. Working agreement

- Work in phases (PROMPT.md §12). **Stop for review after each one.**
- Restate scope and acceptance criteria before starting a phase.
- Write tests alongside the code.
- At the end of a phase, run lint, types and tests, summarise the changes, and list known
  gaps.
- Never stub a critical path silently. If something is unfinished, say so in the phase
  summary.
- Don't edit the owner's `career-inventory.md` without explicit approval.
- Commit at meaningful boundaries. Don't push to GitHub until the privacy scan exists and
  passes.
- Keep this file current. It is the contract, not a snapshot.
