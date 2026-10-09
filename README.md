# Resume Tailor

Paste a job posting; get **two one-page PDF resumes tailored to it** (English and
Turkish), generated from your own LaTeX resume, plus a keyword match report.

- **Truthful by construction.** The model only selects, reorders and rephrases what is in
  your `career-inventory.md`. A deterministic fact guard rejects any number, skill,
  technology or project the inventory cannot back, before anything is rendered.
- **Your layout, untouched.** The model never writes LaTeX. Python renders your own
  macros, and a round-trip test proves the renderer reproduces your base resume exactly.
- **One page, always.** Both languages are compiled with pdfLaTeX and fitted *together*
  by dropping the lowest-priority content, never by shrinking fonts or margins.
- **Private.** Your name, contact details and links never reach an LLM provider: they are
  redacted, and the call aborts if anything personal survives.

> Status: Phase 1 (core + CLI). The GitHub Actions workflow and the web app (for use
> from a phone) come in Phases 2 and 3. See [docs/PLAN.md](docs/PLAN.md).

## Quick start (CLI)

Needs Python 3.12+ and pdfLaTeX (TinyTeX recommended; see below).

```bash
pip install -e .
tailor check --data-dir sample-data                 # validate + test-compile the sample
tailor run --data-dir sample-data --dry-run --posting sample-data/fixtures/posting.txt
```

`--dry-run` replays a recorded LLM answer, so it costs nothing. With your own data:

```bash
tailor run --data-dir ../resume-data --posting posting.txt          # or .pdf, or - for stdin
tailor run --data-dir ../resume-data --posting posting.txt --company "ABC" --position "Veri Bilimci" --note "emphasize iOS"
tailor preset list  --data-dir ../resume-data
tailor preset build --data-dir ../resume-data --stale               # only outdated presets
```

Output lands in `Desktop/Job Applications/<Company> - <Position>/` (OneDrive-redirected
Desktops are handled), and a full copy with the `.tex` sources goes to the data repo.

### Your data folder

```
resume-data/
  base/en/  resume.tex  custom-commands.tex  src/{heading,education,experience,projects,certificates,skills}.tex
  base/tr/  (same structure, Turkish)
  career-inventory.md     every fact you may claim (format: sample-data/career-inventory.md)
  config.yml              owner, providers, models, prices, budget (sample-data/config.yml)
  presets.yml             role-family presets
```

### TinyTeX

Windows (PowerShell): download and run the official installer from
<https://yihui.org/tinytex/>, then install the packages in
[.github/actions/setup-tinytex/packages.txt](.github/actions/setup-tinytex/packages.txt):

```powershell
tlmgr install babel-english babel-turkish cm-super enumitem fancyhdr fontawesome5 fontaxes lato marvosym mweights preprint titlesec
```

XeLaTeX, LuaLaTeX and Tectonic are not supported: the template uses pdfTeX primitives
that keep the PDF text layer clean for applicant-tracking systems.

## LLM providers and what they cost

Three providers, tried in the order set in `config.yml`. Each is skipped if it has no
credentials:

| Provider | Paid by | Notes |
|---|---|---|
| `anthropic` (default) | **Claude API prepaid credits** | Best quality. Each run's exact cost is in the report and `applications.csv` |
| `claude-code` | **Your Claude Pro subscription** (Claude Code, headless) | Counts against Pro usage limits, not API credits |
| `gemini` | **Gemini API free tier** | Rate-limited; free-tier data may be used by Google. Redaction protects your contact details |

**Plain facts about billing:**

- The **Claude API is billed separately from a Claude Pro subscription**. It is prepaid:
  you buy credits, they **expire one year after purchase** and are non-refundable. With
  **auto-reload off**, the balance is a hard spending cap. (Max and Team plans include
  monthly API credits that expire at the end of each billing cycle.)
- The `claude-code` provider uses the **Pro subscription** instead of API credits.
- A **Google AI Pro (Google One) subscription does not include Gemini API usage**. The
  free tier is a separate, rate-limited offer, and its data terms differ from paid use.

A typical run costs about **$0.10–0.15** on `claude-sonnet-5-5`, so a `monthly_budget_usd`
of 5 covers roughly 30–45 applications. Before each run, a budget guard sums this
month's spend in `usage.csv`. If the run would exceed the budget, it skips the Claude API
and uses the next provider. When credits run out, the tool says so and falls back the
same way.

### Setting up the Claude API

1. Create a Claude Console account at <https://platform.claude.com>.
2. **Settings → Billing → Buy credits** (for example $10). Leave **auto-reload off**.
   Credits expire one year after purchase and are non-refundable.
3. Create an API key in a dedicated workspace named `resume-tailor`.
4. Put it in a local `.env` file (never committed) as `ANTHROPIC_API_KEY=...`. For GitHub
   Actions (Phase 2), add it as the repository secret `ANTHROPIC_API_KEY`.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests scripts && mypy && pytest
RT_DATA_DIR=../resume-data pytest              # also run the real-data tests
python scripts/privacy_scan.py --data-dir ../resume-data
```

Tests never call a live LLM: sockets are blocked and API keys are removed in
`tests/conftest.py`.

## License

MIT (added in Phase 5). The LaTeX template in `sample-data/base` is based on the MIT-
licensed resume template credited in its header.
