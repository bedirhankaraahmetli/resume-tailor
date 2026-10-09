# resume-data (private)

The private half of [Resume Tailor](https://github.com/bedirhankaraahmetli/resume-tailor).
**Keep this repository private.** It holds your resumes, your career inventory and every
application you make.

| Path | What it is |
|---|---|
| `base/en`, `base/tr` | Your LaTeX resumes. Never edited by the tool |
| `career-inventory.md` | Everything the tool may claim about you, and nothing else |
| `config.yml` | Your contact strings (for redaction), models, prices, budget |
| `presets.yml` | Ready-made resumes per role family |
| `requests/` | One JSON file per request. Pushing one starts a build |
| `results/` | One JSON file per request: status, files, cost, errors |
| `applications/`, `presets/` | The PDFs and match reports |
| `applications.csv`, `usage.csv` | Your application log and the per-call spend ledger |

## Secrets (Settings → Secrets and variables → Actions)

| Secret | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | The default provider (prepaid Claude API credits) |
| `CLAUDE_CODE_OAUTH_TOKEN` | Optional fallback: your Claude Pro/Max plan. Create it with `claude setup-token` |
| `GEMINI_API_KEY` | Optional fallback: Gemini's free tier |

From a PC with the tool installed, `tailor keys set anthropic --github OWNER/resume-data`
checks a key and stores it here without the value ever being shown.

## Making a request by hand

Commit a file like this to `requests/<id>.json` (the id is also the file name):

```json
{ "schema_version": 1, "type": "application", "id": "20261009-141205-abc-firm",
  "posting": { "text": "…the job posting…" },
  "company": null, "position": null, "provider": null, "model": null, "note": null }
```

Presets: `{ "schema_version": 1, "type": "preset", "id": "…", "presets": "stale" }`
(or `"all"`, or a list of preset ids).
