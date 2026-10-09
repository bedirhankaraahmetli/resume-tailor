# Resume Tailor — Plan

Status: **Phase 0 approved, Phase 1 built** (2026-10-09). §0 records the decisions and
what Phase 1 changed. The rest is the Phase 0 plan as reviewed: scope, acceptance
criteria, design problems found, repo layouts and the JSON schemas. `CLAUDE.md` at the
repo root is the companion contract.

---

## 0. Decisions (owner, 2026-10-09) and Phase 1 notes

**Answers to §3:**

| # | Decision |
|---|---|
| 1 | Real data lives in `Desktop/Projects/resume-data/`, **outside this public repo**. It becomes the private repo in Phase 2 and holds `base/{en,tr}`, `career-inventory.md`, `config.yml`, `presets.yml`, and `reference/` (the original zips and PDFs) |
| 2 | `claude-haiku-4-5` for analysis; `claude-sonnet-5-5` with effort `medium` for tailoring |
| 3 | The PAT is encrypted with a passphrase in the web app (Phase 3) |
| 4 | `usage.csv` is the spend ledger |
| 5 | The base bullets are plain text (the only `\textbf` is the course label), so **no markup is allowed in bullets** |
| 6 | Education has a "Relevant Courses" line. Only the course list is tailored; the entry itself is copied from the base |
| 7 | Fit follows PROMPT.md §5.5; beyond that, certificates and then courses are trimmed, then the run fails clearly. Fonts, margins and spacing are never touched |
| 8 | TinyTeX is installed at `%APPDATA%\TinyTeX` (TeX Live 2026, pdfTeX 1.40.29) |
| 9 | GitHub user: `bedirhankaraahmetli` |
| 10 | Git is initialised locally now; GitHub repos are created and pushed in Phase 2, after the privacy scan passes. The public repo commits with the GitHub no-reply email, not the university address |

**What the real data taught Phase 1** (each item is now in code and tests):

- **The base page is full.** Both bases leave about 1% of the page empty, so tailoring can
  never add without removing, and the fit loop works on every run.
- **Headings can be too wide without the page overflowing.** A long title plus 7 stack
  items pushed the link into the margin ("SHAPGitHub"), and the page count could not see
  it. pdfLaTeX's `Overfull \hbox … in alignment` warnings are now mapped back to the
  project. The fit loop drops that project's trailing stack items first, and a final build
  with any overflow fails.
- **Version numbers are names, not counts.** "Dart 3" let "3 apps" pass the number check.
  Stack lines are no longer citable, and the guard removes known versioned names
  ("Java 21", "JUnit 5") before counting.
- **Evidence must come from positive text only.** The inventory's own "never claim:
  AWS/GCP" line made the report call AWS "evidenced". Evidence now comes from
  `Catalog.evidence_text()`, which excludes every negative sentence.
- **pypdf splits words at kerning pairs** in Lato ("PyT orch", "T urkish"). Keyword checks
  fall back to a space-insensitive match for terms of 4+ characters.
- **The GitHub username is the owner's name**, so every project URL identifies them. All
  URLs are stripped before any LLM call; the renderer re-attaches links by id.
- **Projects that are not on the base resume have no Turkish title.** The LLM supplies
  `title_en`/`title_tr` for those only. Base projects keep their base titles byte for byte.
- **Experience and project headers are copied from the base**, not the inventory, because
  the Turkish forms of employer names and dates (e.g. "Tem 2023") exist only there.
- **`in-progress` projects without explicit permission are not usable**, as the spec
  says. Add `- Resume use: allowed` to an inventory entry to opt in.

**Verified facts behind provider choices** (researched 2026-10-09):

- **Claude Code:** `claude -p --output-format json --json-schema …` returns the result in
  `structured_output`. `--bare` ignores `CLAUDE_CODE_OAUTH_TOKEN`, so isolation uses an
  empty temp dir, `--tools ""`, `--setting-sources ""` and `--strict-mcp-config`.
  `ANTHROPIC_API_KEY` is removed from the child environment, so the subscription is used
  rather than API credits.
- **Gemini:** `gemini-3.8-flash` (free tier, structured output) is called with
  `response_json_schema`. The SDK does not honour `retryDelay`, so we parse RetryInfo
  ourselves.

**API key management** (owner request, 2026-10-09):

- **CLI (built in Phase 1).**
  - `tailor keys list` shows each key, masked, and where it comes from.
  - `tailor keys set <provider>` takes the key as hidden input. It verifies it with a free
    model-list call and saves it to `.env`. With `--github OWNER/REPO` it also stores the
    key as an Actions secret through `gh secret set` (the value goes over stdin only).
  - `tailor keys check` re-verifies the stored keys; `tailor keys remove` deletes one.
- **Web app (Phase 3): Settings → API keys.** One write-only field per provider
  (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`). It shows whether each
  secret exists and when it was last updated, from `GET /repos/{repo}/actions/secrets`,
  which returns names and dates, never values.
  - **Saving:** fetch the repo's Actions public key, encrypt the value in the browser
    with a libsodium sealed box (bundled, never loaded from a CDN), then `PUT` the secret.
    The value lives only in the form field until it is sent, and is never written to
    localStorage, IndexedDB or a log.
  - **This needs one more PAT permission:** "Secrets: Read and write" on the data repo.
    It is optional. Without it the panel shows a link to the repo's secrets settings
    page instead.
  - **Deliberate exception to "keys never reach the browser":** a key typed here passes
    through the page once, on its way to GitHub. It is still never stored or readable
    there. Reading a key back is impossible by GitHub's design, so the panel can only
    replace a key.
  - **Expiry reminder:** the panel can't know when a key expires, so the owner can
    record an optional "expires on" date per key (stored in localStorage, not secret).
    The panel warns 3 days before it.

**Layout change from §4.1:** modules are flat (`models.py`, `guard.py`, `fit.py`, …)
instead of sub-packages, except `providers/`. `init-data-repo`, the reusable workflow and
the caller template are Phase 2.

### Phase 2 notes (2026-10-09)

**Every run builds every pending request**, not only the request in its trigger. This
replaces "the request path as input" from PROMPT.md §8.
- **Why:** GitHub keeps at most one *pending* run per concurrency group and cancels older
  pending runs. With three quick submissions, the middle one's run is cancelled and never
  starts.
- **Pending means** there is no `results/<id>.json` yet. A failed request still gets one,
  so it is never retried automatically, because a retry spends credits again. The
  `request` input of `workflow_dispatch` rebuilds one file on purpose.
- **The data checkout is the branch tip,** not the triggering commit. A run that waited in
  the queue must see the results the previous run pushed, or it builds them again.
- **For the web app (Phase 3):** treat `results/<id>.json` as the source of truth. The run
  started by your own commit may be the one that was cancelled, and another run built the
  request.

**The stages are separate CLI calls** (`tailor request start|analyze|tailor|compile|finish`).
- They share a checkpoint at `$RUNNER_TEMP/rt-work/queue.json`, outside the data repo, so
  it is never committed.
- That checkpoint holds the analysis, the tailoring, the router's responses and the
  notices.
- `tailor run` runs the same three stage functions in one process, so the two paths cannot
  drift apart.
- **The step names are a contract with the web app:** `Analyze posting`, `Tailor`,
  `Compile and check`, `Publish`.

**Smaller decisions.**
- **Preset requests:** a preset request is one job per preset, reported in one result file
  with a `runs` list.
- **Interrupted runs:** if a run is cancelled or times out, `Publish` (`if: always()`)
  still writes a failed result that names the step it stopped in.
- **Pinning:** the caller pins the tool to a **commit SHA**, not a tag, because tags can
  be moved. `init-data-repo` defaults to the checkout's `HEAD`.
- **Claude Code** is installed in CI only when `CLAUDE_CODE_OAUTH_TOKEN` is set.
- **Push races:** the Publish step does `git pull --rebase` with 5 retries. A real
  conflict, for example the web app editing `applications.csv` at the same moment, still
  fails the push. Phase 3's CSV edits should retry on their side (§2.10).

### Phase 3 notes (2026-10-09)

**`presets/status.json` comes from the workflow.** The browser cannot compute a preset's
status. The input hash includes the preset's YAML entry in Python's canonical JSON form,
and reproducing that would need a YAML parser in the page. So `tailor request finish`
writes the file on every run. The data repo's workflow also starts on pushes to `base/**`,
`career-inventory.md` and `presets.yml`, only to refresh it. Those runs make no LLM call
and take about 25 s.

**Web dependencies (runtime):**
- `pdfjs-dist`, for posting text and PDF previews. It is lazy-loaded, about 130 KB
  gzipped.
- `tweetnacl` and `blakejs`, for the libsodium sealed box that GitHub requires for
  secrets. WebCrypto has X25519 but not XSalsa20-Poly1305.

All three have zero dependencies. `libsodium-wrappers` is a dev dependency only; a test
uses it to open our sealed box.

**Verified in a browser** (an isolated headless Chrome, both the local build and the
deployed site):
- Settings: saving and testing; the token is encrypted in localStorage and plain only in
  sessionStorage.
- Unlocking, with a wrong and then the right passphrase.
- History; the folder and result views, with both PDF previews and the report.
- Quick apply; PDF text extraction.
- Desktop and iPhone widths, in dark mode.
- No CSP violations.

**Not verified by me:**
- A live submission with real step-by-step status, because it spends credits. It is the
  owner's acceptance test.
- Save to folder, which needs a real directory picker.
- The iPhone share sheet.
- Saving an API key, which would overwrite the real secret. The sealed box is
  unit-tested against libsodium.

**pdf.js renders through `requestAnimationFrame`.** That is paused in hidden tabs, so a
preview started in a background tab finishes when the tab is shown. This is harmless for
users, but it made headless tests hang until the tab was brought to the front.

**Owner's test (2026-10-09): accepted on Windows and iPhone.** The test led to these
changes:
- Keyword matching:
  - It ignores generic words but keeps the rest of a term as a phrase.
  - It counts either PDF, and maps Turkish terms back through `skill_names_tr`.
  - The must-have warning checks the English PDF only.
- The share sheet sends the report as `.txt`. `.md` made the whole share fail with
  "Permission denied".
- Base resume PDFs are in Quick apply (`base-pdf/`, `tailor base build`).
- The theme is light blue.
- Owner-approved inventory edits: new skills, a Soft Skills row on both base resumes,
  and a tighter Turkish SHAP bullet so the row fits.

### Phase 4 backlog (owner, 2026-10-09)

From PROMPT.md §12:
- an optional cover letter;
- status editing in History;
- "regenerate with a note".

Added by the owner:
- **Skills editor in the web app (Settings → Skills).**
  - **Input:** the skill (Title Case), its Turkish name, and an evidence note.
  - **One commit** updates both files:
    - a row in `career-inventory.md` §6;
    - a `skill_names_tr` line in `config.yml`.
  - **Writes:** through the Contents API with each file's `sha`, retrying on 409, like
    `appendApplication`.
  - **Checks first:**
    - a near-duplicate (case-insensitive, or one name containing the other, e.g.
      "Data Analysis" vs "Data Visualization");
    - an empty Turkish name;
    - a name that is on the "never claim" list.
  - **Says what happens next:** presets go outdated, and the base resume does not
    change.
  - **Editing YAML in the browser:** do not add a YAML library. Insert the line after
    the last `skill_names_tr:` entry, and test against the real file's shape.
  - **Pending:** the owner has three skills to add: Data Analysis, Documentation and
    Willingness to Learn.

Declined by the owner:
- LinkedIn link import and a bookmarklet. Postings stay pasted.
- Opting Crumble (4.7) into resumes.

---

## 1. Scope (restated)

One action (CLI, or the web app from a Windows PC or an iPhone) turns a pasted job posting
into:

- `<Owner>_<Position>_Resume.pdf` (EN) and `..._Ozgecmis.pdf` (TR), one page
  each, generated from the existing LaTeX base resumes, with the layout untouched and only
  content selected, reordered and rephrased;
- `match-report.md` (keyword coverage, evidence-backed misses, real gaps, changes, provider,
  model, exact cost);
- a row in `applications.csv`;

in `Desktop/Job Applications/<Company> - <Position>/` on Windows, or in Files on iPhone.

It also keeps one ready-made EN+TR pair per role-family preset, marked outdated by input
hash and rebuilt only on request.

**Two repos.** `resume-tailor` (public): Python core + CLI, reusable workflow, Pages web app,
fictional sample data, tests, docs. `resume-data` (private): real data, requests, outputs,
logs, a caller workflow, the API secrets.

**Three LLM providers** behind one interface, in this fallback order: `anthropic` (prepaid API
credits), then `claude-code` (Pro subscription, headless), then `gemini` (free tier).
Redaction applies to all three.

**Out of scope:** paid hosting, any server, any LLM call from the browser, XeLaTeX, LuaLaTeX
and Tectonic, and edits to `resume.tex` and `custom-commands.tex`.

### Acceptance criteria (from PROMPT.md §13, made testable)

| # | Criterion | How it is verified |
|---|---|---|
| A1 | One action from Windows or iPhone yields both PDFs in the right place | Manual: Phase 3 run on both devices |
| A2 | Both PDFs are exactly 1 page, layout identical to the base, ATS check passes | `pypdf` page count; **identity round-trip test** (§6.3); ATS checker |
| A3 | No fact, number, skill or tech outside the inventory | Fact guard on every run; unit tests per rule |
| A4 | 3 presets exist; outdated after any input change; rebuilt only on request | Hash-manifest tests; `preset list` output |
| A5 | Naming exact; a Turkish posting with an English title keeps the English title | Naming unit tests (table-driven) |
| A6 | No paid infra; every run's exact cost is shown in the report, the CSV and the web app; fallbacks keep working when credits or budget run out | Cost from `usage`; billing-error and budget-guard tests with mocks |
| A7 | No contact details or real name reach any provider | Redaction tests against the real `config.yml` strings; fail-closed abort |
| A8 | Public repo has no personal data and no secrets | gitleaks + `scripts/privacy_scan.py` in CI |

---

## 2. Design problems found in Phase 0

The architecture holds. Nothing below blocks it, but each item changes a detail. **Items marked
⚠️ need your decision** (also listed in §3).

### 2.1 ⚠️ Model ids in the prompt are partly wrong

Checked against Anthropic's model table (cached 2026-09-25):

| Model | Id | Input | Output | Cache write (5 min) | Cache read |
|---|---|---|---|---|---|
| Sonnet 5.5 (tailor) | `claude-sonnet-5-5` | $2.00 | $10.00 | $2.50 | $0.20 |
| Haiku 4.5 (analyze) | `claude-haiku-4-5` | $1.00 | $5.00 | $1.25 | $0.10 |

Prices are per million tokens. Cache writes are 1.25× input; the reads are as published.

- **`claude-haiku-5-5` does not exist.** The current Haiku is `claude-haiku-4-5`. I will use
  it for `analyze_model`.
- **Sonnet 5.5 rejects forced tool use** (`tool_choice: any/tool` → 400). So structured JSON
  comes from **structured outputs** (`output_config.format`, via the SDK's
  `messages.parse()` with the Pydantic model). Haiku 4.5 supports structured outputs too, so
  both calls use one mechanism.
- Sonnet 5.5 thinks adaptively by default and can't turn thinking off (except
  `between_tools`). Thinking is billed as output, so I'll set `effort` in `config.yml` and
  start at `medium` for tailoring.
- **Out of credits** is HTTP 402 with error type `billing_error`. I detect it by the SDK's
  typed error and `.type`, never by matching message text.
- I'll re-check the pricing page on the day Phase 1 writes `config.yml` and date the table.

### 2.2 Estimated cost per run (so the $5 budget has a meaning)

These are rough figures, to be replaced by measured ones in Phase 1. I assume the inventory
plus both bases are about 15k tokens, the output (EN+TR JSON) about 5k, and thinking about
3k.

- Tailor on Sonnet 5.5: roughly $0.03 input + $0.08 output, so **about $0.10–0.15**.
- Analyze on Haiku 4.5: about **$0.01**.
- With one repair round, add about 60%.

So `monthly_budget_usd: 5` buys roughly 30–45 tailored applications. Switching `tailor_model`
to Haiku cuts that by about half.

**Prompt caching is not free here.** A cache write costs 1.25× and only pays back if a read
follows within 5 minutes. A single application run reads it back only during the repair
round. Preset builds (3 in a row) and repairs benefit; isolated runs pay about +25% on the
static part. Plan: cache the static block (rules, inventory, bases) and put it first in a
stable order, so repairs and batches hit it. Then measure, and drop caching for single runs
if it doesn't pay. I'll report the measured hit rate in Phase 1.

### 2.3 Budget needs a spend ledger, not only `applications.csv`

The budget must count preset builds, which by spec are not in `applications.csv`. It must
also count **failed runs**: a run that dies in the fact guard has still spent credits. Summing
`applications.csv` alone would under-count.

**Proposal:** add `usage.csv` to the data repo, with one row per LLM call: timestamp, run id,
kind (application / preset / repair), provider, model, the token counts, and `cost_usd`. The
budget guard sums this month's rows. `applications.csv` keeps its per-application `cost_usd`
as the sum of that run's rows.

### 2.4 Fitting must be joint across EN and TR

The rule is the same selection in both languages, but Turkish runs longer. If each language
were fitted on its own, TR would drop a bullet that EN keeps.

**So the fit loop compiles both, and a drop applies to both.** It stops only when both are
one page. It adds a reserve bullet only if both have more than 12% empty and both still fit
afterwards.

Drop order:
1. The lowest-`priority` bullet. Each experience and project keeps at least one bullet.
2. The lowest-ranked project, while more than 3 projects remain.
3. The trailing certificates, then trailing courses (if the base lists courses).
4. If it still doesn't fit, **fail with a clear message**. Never shrink fonts or margins.

To measure "empty", I take the lowest text baseline on the page from `pypdf`'s text visitor
(no extra dependency). Empty fraction = (y_min − bottom margin) / usable height.

### 2.5 The renderer must reproduce the base framing exactly

I haven't seen the base `src/*.tex` files yet. They will contain more than items: section
titles (`\section{Projects}` / `\section{Projeler}`), list start and end macros, perhaps
`\vspace` tweaks.

**Approach:** read each base `src/*.tex` as a frame, made of prefix + item region + suffix.
Keep the frame byte-for-byte and regenerate only the item region with the documented macros.

The strongest layout test is an **identity round-trip**: render the base resume's *own*
content through the renderer and get the same `.tex`, after whitespace normalisation. If that
holds, tailoring cannot change the layout, only the content.

### 2.6 ⚠️ Fact-guard edge cases: number formats and spelled-out numbers

"Every number in a bullet must appear in the cited source" needs normalisation, or it will
false-fail on Turkish:

- `%15` ↔ `15%`
- `1.000` ↔ `1,000`
- `0,85` ↔ `0.85`
- `3x` ↔ `3×`
- years and date ranges
- spelled-out small numbers in both languages (`three` / `üç`)

Spelled-out numbers count as numbers. An LLM writing "three apps" where the source says
"two" is exactly the error the guard exists for.

Skills and stack items match against a canonical list with aliases (`JS` = `JavaScript`). A
term not in the inventory fails even if it is "obviously true".

### 2.7 ⚠️ PAT storage on GitHub Pages: the origin is shared

All your project Pages sites share **one origin** (`<user>.github.io`), so they share one
`localStorage`. Any other Pages project of yours, now or later, including a fork's demo,
could read a PAT stored in plain text.

Also, Pages can't send HTTP headers, so the CSP has to be a `<meta http-equiv>` tag. That
works for `script-src` and `connect-src`, but not for `frame-ancestors`.

**Proposal:** encrypt the PAT at rest with a passphrase (WebCrypto: PBKDF2 → AES-GCM). Keep
it decrypted only in `sessionStorage` for the tab's life. You type the passphrase once per
session; on iPhone that is once per Safari tab. A fine-grained PAT scoped to one repo with a
short expiry limits damage either way.

The alternative is to accept plain `localStorage` and never host another Pages project on
that account.

### 2.8 Redaction gaps beyond name, phone and email

- **GitHub username inside project URLs** (`github.com/<you>/...`) identifies you. All URLs
  are stripped from LLM input. Projects are referred to by inventory id, and the renderer
  re-attaches links (as the spec already says).
- **Turkish suffixed name forms** (e.g. "Yılmaz'ın") and both casings
  (`İ/I`). The name regex covers a suffix after an apostrophe, and Turkish-aware casefolding.
- **The fail-closed check** runs on the *final serialized request body*, not the inputs, so a
  leak through a prompt template or the note field is also caught.
- **Known limit, stated plainly:** university, dates and employers together can still
  re-identify a person. The spec only requires contact details and name, and the tailoring
  needs those facts.

### 2.9 Status reporting and results for the web app

The Actions API exposes job **steps**. So the workflow runs `analyze`, `tailor`, `compile`
and `publish` as separate named steps (one CLI subcommand each, sharing a work dir). The web
app maps the steps to queued → analyzing → tailoring → compiling → done.

The workflow also commits `results/<request-id>.json`, holding the status, the folder, the
file paths, the cost, the provider, the model, and any error. The web app reads that file
instead of guessing folder names. It sits outside `requests/**`, so it can't retrigger.

### 2.10 Loops, races and concurrent CSV writes

- **No loops:** commits made with `GITHUB_TOKEN` don't trigger workflows, and the trigger is
  path-filtered to `requests/**.json`. Both protections apply.
- **Requests in flight:** they are serialised by `concurrency: group: tailor,
  cancel-in-progress: false`.
- **Web-app commits:** "Log this application" and History status edits change
  `applications.csv` through the Contents API with the file's `sha`. On 409/422 the app
  re-reads, re-applies and retries. The workflow does `git pull --rebase` before pushing.

### 2.11 `claude-code` provider: isolate it

Headless Claude Code reads `CLAUDE.md` files and settings from its working directory and
parent folders. On this PC, `Desktop/CLAUDE.md` (DoseClock's) would leak in.

So it runs:
- in an **empty temp dir**;
- with all tools disabled and a single turn;
- with its own system prompt;
- with the redacted payload on stdin;
- with JSON output validated by the same Pydantic models.

I'll confirm the exact current flags (`-p`, `--output-format json`, the schema, tool and
settings-source flags) against the Claude Code docs at the start of Phase 1. The flags have
changed often.

### 2.12 Gemini free tier

I'll pick the model from Google's current free-tier rate-limit table at the start of Phase 1
(a Flash-class model with response-schema support) and put it in `config.yml`. 429 handling
honours `retryDelay` from the error details.

### 2.13 Local toolchain on this PC

`pdflatex` is **not installed**. `claude` isn't on the shell PATH (the VS Code extension
carries its own). Python 3.12 and 3.13, Node 22, git 2.33 and gh 2.96 are present.

**Recommendation:** install **TinyTeX on Windows** with the same package list as CI, so local
and CI compile identically. MiKTeX's on-the-fly installs are a parity risk.

---

## 3. Open questions (need your answer before Phase 1)

1. **Your files.** Where are `base/en`, `base/tr` and `career-inventory.md`? I need the real
   inventory format before writing the parser and its tests. If convenient, put them in a
   folder *outside* this repo, such as `Desktop/Projects/resume-data/` (it becomes the private
   repo later).
2. **Models (§2.1):** OK to use `claude-haiku-4-5` for analysis, `claude-sonnet-5-5` for
   tailoring, effort `medium`?
3. **PAT storage (§2.7):** passphrase-encrypted (recommended), or plain `localStorage`?
4. **Spend ledger (§2.3):** OK to add `usage.csv` to the data repo?
5. **Bold in bullets:** do your base bullets use `\textbf{...}` for key terms? If so, I'll
   allow one markup only, `**term**`. The renderer turns it into `\textbf` *after* escaping,
   and the term must be a known skill. Otherwise bullets are plain text.
6. **Education:** is there a "Relevant coursework" line or GPA? I plan to keep entries
   verbatim and only select and reorder courses (if present).
7. **Fit fallback (§2.4):** OK that the last resort is "fail with a clear message", never
   touching fonts, margins or spacing?
8. **TinyTeX locally (§2.13):** OK to install it (user-level, about 300 MB with these
   packages)?
9. **Your GitHub username:** used for the reusable-workflow reference, the Pages URL and the
   privacy scanner's allow and deny lists.
10. **Git:** OK if I `git init` this folder at the start of Phase 1 (local commits only), and
    create and push the GitHub repos in Phase 2, after the privacy scan exists and passes?

---

## 4. Repo layouts

### 4.1 `resume-tailor` (public)

```
resume-tailor/
  pyproject.toml              # package `resume_tailor`, console script `tailor`
  CLAUDE.md  README.md  LICENSE  .gitignore  .gitleaks.toml
  src/resume_tailor/
    cli.py                    # argparse: run, check, init-data-repo, preset build|list,
                              #   plus step subcommands (analyze/tailor/compile/publish) for CI
    config.py                 # config.yml + presets.yml → Pydantic
    paths.py                  # Desktop resolution (Known Folder API on Windows), out dirs
    models/                   # Pydantic: inventory, analysis, tailoring, request, result,
                              #   manifest, usage
    inventory/parser.py       # career-inventory.md → Inventory
    redaction.py              # scrub + fail-closed check on the serialized payload
    providers/
      base.py                 # Provider protocol, typed errors (Billing, RateLimit, Invalid…)
      anthropic_provider.py   # messages.parse + output_config, cache_control, usage → cost
      claude_code.py          # headless subprocess, isolated temp dir, no tools
      gemini.py               # google-genai, response schema, retryDelay backoff
      router.py               # order, credentials present?, budget guard, fallback, ledger
      pricing.py
    pipeline/
      analyze.py  tailor.py  repair.py  run.py  preset.py
    guard/facts.py  guard/numbers.py  guard/aliases.py
    render/escape.py  render/frames.py  render/sections.py
    build/compile.py  build/fit.py  build/measure.py
    checks/ats.py  checks/keywords.py   # Turkish-aware casefold, word boundaries, C++/C#/.NET
    report/match_report.py
    io/naming.py  io/posting.py  io/csvlog.py  io/hashing.py
    scaffold/init_data_repo.py
    scaffold/templates/       # config.yml, presets.yml, caller workflow, .gitignore, README
  prompts/
    analyze.v1.md  tailor.v1.md  repair.v1.md  preset.v1.md  rules.v1.md
  sample-data/                # fictional person "Deniz Yılmaz" — full mirror of resume-data
    base/en/…  base/tr/…  career-inventory.md  config.yml  presets.yml
    fixtures/                 # recorded LLM responses for --dry-run and tests
  tests/
    unit/  golden/  integration/   # integration skips without pdflatex
    conftest.py               # blocks all sockets; live test needs RT_LIVE_SMOKE=1
  scripts/privacy_scan.py
  web/                        # Vite + TS, no framework
    index.html  vite.config.ts  src/{main,github,crypto,fsaccess,share,views/*}.ts
  .github/workflows/
    tailor.yml                # reusable (workflow_call)
    ci.yml                    # ruff, mypy, pytest, privacy scan, gitleaks
    pages.yml                 # build web/ → Pages
  docs/PLAN.md  docs/SETUP.md  docs/PRIVACY.md
```

**Runtime dependencies (deliberately few):** `anthropic`, `google-genai`, `pydantic`,
`pypdf`, `pyyaml`. No CLI framework (argparse) and no dotenv package (a 15-line `.env`
reader).
**Dev dependencies:** `pytest`, `ruff`, `mypy`.
**Web:** `vite`, `typescript`, `pdfjs-dist` (bundled; no CDN at runtime).

### 4.2 `resume-data` (private)

As in PROMPT.md §3, plus:

```
resume-data/
  base/en/…  base/tr/…  career-inventory.md  config.yml  presets.yml
  requests/<id>.json          # trigger (written by web app or CLI)
  results/<id>.json           # NEW: run outcome for the web app (§2.9)
  applications/<Company - Position>/{*.pdf, match-report.md, _build/}
  presets/<folder>/{*.pdf, match-report.md, manifest.json, _build/}
  applications.csv
  usage.csv                   # NEW: per-LLM-call spend ledger (§2.3)
  .github/workflows/tailor.yml
```

---

## 5. Schemas

All schemas are Pydantic models in `models/`. The JSON Schema sent to providers is generated
from them, so there is one source. The examples below are illustrative.

### 5.1 Posting analysis (LLM call 1)

```json
{
  "company": "ABC Firm",                    // null if not stated
  "position": "Data Scientist",             // verbatim from posting
  "posting_language": "tr",                 // "en" | "tr" | "other"
  "seniority": "junior",                    // intern|junior|mid|senior|lead|unspecified
  "must_have": ["Python", "SQL", "machine learning"],
  "nice_to_have": ["Docker"],
  "keywords": [
    { "term": "machine learning", "synonyms": ["ML", "makine öğrenmesi"],
      "importance": "must" }               // must | nice ; 15–30 items
  ]
}
```

A manual `--company` / `--position` overrides the analysis. For presets there is no call: the
preset's `position` and `focus` stand in, with `keywords` = [].

### 5.2 Tailoring output (LLM call 2)

The design rule: **the LLM chooses ids and writes prose; Python owns every fact it can.**
Dates, employers, titles, URLs, certificate names and education entries are never in the
output. The renderer pulls them from the inventory by id.

```json
{
  "schema_version": 1,
  "experience": [                           // order = display order; every entry required
    { "id": "3.1",
      "bullets": [ /* Bullet */ ] }
  ],
  "projects": [                             // order = rank; ≥3 when inventory has ≥3 usable
    { "id": "4.2",
      "stack": ["Swift", "SwiftUI", "XCTest"],   // ⊆ inventory stack of 4.2, ≤ 7
      "bullets": [ /* Bullet */ ] }
  ],
  "education": [ { "id": "2.1", "courses": ["Machine Learning", "Databases"] } ],
  "certificates": ["5.3", "5.1"],           // ids, ordered
  "skills": [
    { "group_en": "Languages", "group_tr": "Diller",
      "items": ["Python", "Swift", "Java"] }    // each ⊆ inventory skills
  ],
  "reserve": [ { "parent": "4.2", "bullet": { /* Bullet */ } } ],  // best first
  "changes": [ "Moved the recommender project to first place (matches 'recommender systems')" ],
  "gaps": [ "Kubernetes: no evidence in inventory" ]
}
```

**Bullet**

```json
{
  "sources": ["4.2"],                       // inventory section ids the facts come from
  "priority": 1,                            // 1 = keep longest … 5 = drop first
  "en": "Built a ... with 92% accuracy",    // plain text (optionally **term**, see Q5)
  "tr": "... %92 doğrulukla ... geliştirdim"
}
```

**Validated in code after parsing** (fact guard, §2.6, plus structural checks):

- Every id exists. Each project status is allowed (`in-progress` only if the inventory permits
  it, and then the renderer adds the in-progress label).
- Every experience entry is present.
- Each project has between 1 and N bullets.
- The `stack` and skills items are in the inventory.
- No "Do not claim" term appears in `en` or `tr` (casefolded, alias-aware).
- Every number in `en` and `tr` appears in the union of the cited sources' text.
- `tr` is not passive voice. This is a heuristic warning, not a failure, at least in v1: it
  flags `-ldı/-ldi/-ndı/-ndi`-ending verbs at the end of bullets.

On failure: one repair call with the error list. If it fails again, the run fails and the
report and `results/<id>.json` list each violation.

### 5.3 Request file (`requests/<id>.json`)

```json
{ "schema_version": 1, "type": "application",
  "id": "20261009-141205-abc-firm",
  "posting": { "text": "…" },
  "company": null, "position": null,
  "provider": null, "model": null,
  "note": null, "cover_letter": false }

{ "schema_version": 1, "type": "preset", "id": "…", "presets": ["ios-mobile"] }
// or "presets": "stale" | "all"
```

### 5.4 Result file (`results/<id>.json`)

```json
{ "id": "…", "status": "done",              // done | failed
  "folder": "applications/ABC Firm - Data Scientist",
  "files": { "en": "…Resume.pdf", "tr": "…Ozgecmis.pdf", "report": "match-report.md" },
  "provider": "anthropic", "model": "claude-sonnet-5-5", "cost_usd": 0.1234,
  "match_pct": 78, "notices": ["Budget guard: fell back to claude-code"],
  "error": null }
```

### 5.5 Preset manifest

```json
{ "preset_id": "ios-mobile", "built_at": "…", "provider": "…", "model": "…",
  "cost_usd": 0.11, "tool_version": "0.1.0",
  "input_hash": "sha256:…",                 // base/**, career-inventory.md, this preset's entry
  "inputs": { "base/en/src/projects.tex": "sha256:…", "…": "…" } }
```

**Hashing rules:**
- Normalise line endings (CRLF → LF), so a Windows checkout doesn't mark presets outdated.
- Hash the preset's own YAML entry in canonical form, not the whole `presets.yml`, so editing
  one preset doesn't stale the others.

Open choice for you: should a change to the *prompts* or the tool version also mark presets
outdated? My default is **no**. They show "built with tool vX", and only data changes flag
them.

---

## 6. Phase 1 test plan (summary)

1. **Parser:** tests against the real inventory file, plus the sample's.
2. **Naming:** table-driven (Turkish letters, `<>:"/\|?*`, collisions ` (2)`, `Sr. iOS
   Developer`).
3. **Escaping:** every special character and its combinations, and that `**x**` can't smuggle
   in a raw command.
4. **Fact guard:** one test per rule, plus the Turkish number formats.
5. **Fit loop:** uses a fake compiler that reports page counts, so it is tested without TeX.
6. **Keyword matching:** `İ/i`, `I/ı`, `C++`, `C#`, `.NET`, `Node.js`.
7. **Redaction:** uses the real `config.yml` strings, from your data folder, read at test time
   and never copied into the public repo.
8. **Golden:** the sample JSON renders to the expected `.tex`. The **identity round-trip**
   works on both the sample and the real bases.
9. **Integration:** compile, 1 page, ATS check. Skipped without `pdflatex`.
10. **Network:** sockets are blocked in `conftest.py`. A live smoke test runs only with
    `RT_LIVE_SMOKE=1`.

**Before any command that spends credits, I'll state the estimated cost** (§2.2). Development
runs use `--provider claude-code` or `--model claude-haiku-4-5`.
