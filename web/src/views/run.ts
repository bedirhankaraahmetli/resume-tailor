// Live status of one request, then its result.
//
// `results/<id>.json` is the source of truth (docs/PLAN.md §0, Phase 2 notes). The workflow
// run is only used for the progress list before the result exists, and it may not be the
// run that builds the request: GitHub cancels older *pending* runs, and the newest one
// builds every pending request.

import { clear, h, notice, shortDate } from "../dom";
import type { GitHub, WorkflowRun } from "../github";
import { PHASE_LABEL, PROGRESS, phaseOf, type Phase } from "../status";
import { localRuns } from "../store";
import type { RunResult, View } from "../types";
import { noticesList, resultSummary, showFolder } from "./folder";

const POLL_MS = 5000;
const GIVE_UP_MS = 30 * 60 * 1000;

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function progress(phase: Phase): HTMLElement {
  const at = PROGRESS.indexOf(phase === "starting" || phase === "waiting" ? "queued" : phase);
  return h("ol", { class: "progress" }, PROGRESS.map((p, i) => {
    const state = i < at ? "done" : i === at ? "current" : "todo";
    const mark = state === "done" ? "✓" : state === "current" ? "●" : "○";
    return h("li", { class: state, "aria-current": state === "current" ? "step" : undefined },
      h("span", { class: "mark", "aria-hidden": "true" }, mark),
      h("span", null, PHASE_LABEL[p]),
      state === "current" ? h("span", { class: "sr-only" }, " (in progress)") : null);
  }));
}

export async function showRun(view: View, gh: GitHub, id: string): Promise<void> {
  const local = localRuns().find((r) => r.id === id);
  const status = h("div");
  const link = h("p", { class: "muted small" });
  clear(view.el, h("h1", null, "Request"), h("p", { class: "muted mono" }, id), status, link);
  const started = Date.now();
  let lastRun: WorkflowRun | null = null;

  while (view.alive()) {
    const result = await gh.getJson<RunResult>(`results/${id}.json`);
    if (!view.alive()) return;
    if (result) {
      await showResult(view, gh, result);
      return;
    }
    if (local) {
      const runs = await gh.runsForCommit(local.commit);
      lastRun = runs[0] ?? lastRun;
    }
    const steps = lastRun && lastRun.status !== "queued" ? await gh.steps(lastRun.id) : [];
    if (!view.alive()) return;
    const phase = phaseOf(lastRun, steps);
    clear(status,
      progress(phase),
      phase === "waiting"
        ? notice("info", "GitHub replaced this run with a newer one, which builds every "
          + "waiting request, including this one.")
        : notice("info", `${PHASE_LABEL[phase]}…`, " This page updates by itself; you can "
          + "leave and come back."),
      local ? null : notice("warn", "This request was started on another device, so only "
        + "the final result is shown here."),
    );
    clear(link, lastRun
      ? h("a", { href: lastRun.html_url, target: "_blank", rel: "noopener noreferrer" },
        "Open the workflow run on GitHub")
      : local ? `Submitted ${shortDate(local.started)}` : "");
    if (Date.now() - started > GIVE_UP_MS) {
      clear(status, notice("error", "No result after 30 minutes. Check the workflow run "
        + "on GitHub."));
      return;
    }
    await sleep(POLL_MS);
  }
}

async function showResult(view: View, gh: GitHub, result: RunResult): Promise<void> {
  if (result.status === "failed") {
    clear(view.el,
      h("h1", null, "The request failed"),
      resultSummary(result),
      notice("error", h("span", { class: "pre" }, result.error ?? "Unknown error.")),
      noticesList(result.notices),
      result.runs?.length ? presetRuns(result) : null);
    return;
  }
  if (result.kind === "preset") {
    clear(view.el, h("h1", null, "Presets built"), resultSummary(result),
      result.runs?.length ? presetRuns(result) : noticesList(result.notices));
    return;
  }
  await showFolder(view, gh, result.folder ?? "", result);
}

function presetRuns(result: RunResult): HTMLElement {
  return h("ul", { class: "cards" }, (result.runs ?? []).map((r) => h("li", { class: "card" },
    h("strong", null, r.id),
    r.status === "done" && r.folder
      ? h("a", { href: `#/folder/${encodeURIComponent(r.folder)}` }, " Open")
      : h("span", { class: "bad" }, ` failed: ${r.error ?? ""}`))));
}
