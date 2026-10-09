// Shows one output folder of the data repo: both PDFs (preview, download, share, save to
// folder) and the match report. Used for a finished run, a History row and a preset.

import { parseRecords } from "../csv";
import { busy, clear, errorText, h, money, notice } from "../dom";
import type { GitHub } from "../github";
import { requestId } from "../ids";
import { renderMarkdown } from "../markdown";
import { renderFirstPage } from "../pdf";
import {
  canSaveToFolder, canShareFiles, chooseFolder, download, saveToFolder, savedFolderName, share,
  type OutFile,
} from "../save";
import { submit } from "../requests";
import type { ApplicationRequest, RunResult, View } from "../types";
import { PROVIDERS } from "./new";

interface Located {
  en?: string;
  tr?: string;
  report?: string;
}

async function locate(gh: GitHub, folder: string): Promise<Located | null> {
  const entries = await gh.listDir(folder);
  if (!entries) return null;
  const files = entries.filter((e) => e.type === "file").map((e) => e.path);
  return {
    en: files.find((p) => p.endsWith("_Resume.pdf")),
    tr: files.find((p) => p.endsWith("_Ozgecmis.pdf")),
    report: files.find((p) => p.endsWith("match-report.md")),
  };
}

/** `applications/X` → `X`; `presets/X` → `_Presets/X` (PROMPT.md §9);
 * `base-pdf` → `_Base`. */
export function localSubfolder(folder: string): string[] {
  const [top, ...rest] = folder.split("/");
  if (top === "base-pdf") return ["_Base"];
  return top === "presets" ? ["_Presets", ...rest] : rest;
}

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

export function resultSummary(result: RunResult): HTMLElement {
  return h("div", { class: "facts" },
    h("span", null, `${result.provider ?? "–"} · ${result.model ?? "–"}`),
    h("span", null, `Cost ${money(result.cost_usd)}`),
    result.match_pct !== null ? h("span", null, `Keyword match ${result.match_pct}%`) : null,
  );
}

export function noticesList(notices: string[]): HTMLElement | null {
  if (!notices.length) return null;
  return h("details", { class: "card" },
    h("summary", null, `Notes from the run (${notices.length})`),
    h("ul", { class: "plain" }, notices.map((n) => h("li", null, n))));
}

export async function showFolder(view: View, gh: GitHub, folder: string,
                                 result?: RunResult): Promise<void> {
  const title = folder === "base-pdf" ? "Base resume" : basename(folder);
  const status = h("div", null, notice("info", "Loading files…"));
  clear(view.el, h("h1", null, title), result ? resultSummary(result) : null, status);

  const found = await locate(gh, folder);
  if (!view.alive()) return;
  if (!found || (!found.en && !found.tr)) {
    clear(status, notice("error", `No PDFs found in ${folder}.`));
    return;
  }
  const [en, tr, report] = await Promise.all([
    found.en ? gh.getBytes(found.en) : null,
    found.tr ? gh.getBytes(found.tr) : null,
    found.report ? gh.getText(found.report) : null,
  ]);
  if (!view.alive()) return;
  clear(status);

  const files: OutFile[] = [];
  const pdfs: [string, string | undefined, Uint8Array | null][] = [
    ["English", found.en, en], ["Türkçe", found.tr, tr]];
  for (const [, path, data] of pdfs) {
    if (path && data) files.push({ name: basename(path), data, type: "application/pdf" });
  }
  if (report) {
    files.push({ name: "match-report.md", data: new TextEncoder().encode(report.text),
      type: "text/markdown" });
  }

  view.el.append(actions(folder, files, title));

  const grid = h("div", { class: "pdf-grid" });
  view.el.append(grid); // in the page first, so the frames have a width to render at
  for (const [label, path, data] of pdfs) {
    if (!path || !data) continue;
    const file: OutFile = { name: basename(path), data, type: "application/pdf" };
    const frame = h("div", { class: "pdf-frame" }, h("span", { class: "muted" }, "Rendering…"));
    grid.append(h("section", { class: "card pdf-card" },
      h("h2", null, label),
      frame,
      h("div", { class: "row" },
        h("button", { class: "secondary", onclick: () => download(file) }, "Download PDF"),
        h("span", { class: "muted small" }, file.name)),
    ));
    renderFirstPage(data, Math.min(frame.clientWidth || 360, 560))
      .then((canvas) => clear(frame, canvas))
      .catch((e: unknown) => clear(frame, notice("warn", `Preview unavailable: ${errorText(e)}`)));
  }

  if (folder.startsWith("applications/")) view.el.append(regenerateCard(gh, folder, result));

  if (result) {
    const n = noticesList(result.notices);
    if (n) view.el.append(n);
  }
  if (report) {
    const body = h("div", { class: "report" });
    body.innerHTML = renderMarkdown(report.text); // escaped first; see markdown.ts
    view.el.append(h("details", { class: "card", open: true },
      h("summary", null, "Match report"), body));
  }
}

function actions(folder: string, files: OutFile[], title: string): HTMLElement {
  const out = h("div");
  const row = h("div", { class: "row actions" });
  const sub = localSubfolder(folder);

  if (canSaveToFolder()) {
    const save = h("button", { class: "primary" }, "Save to folder");
    save.addEventListener("click", busy(save, out, async () => {
      const where = await saveToFolder(sub, files);
      clear(out, notice("ok", `Saved ${files.length} files to ${where}`));
    }));
    const change = h("button", { class: "link" }, "Change folder");
    change.addEventListener("click", busy(change, out, async () => {
      const handle = await chooseFolder();
      clear(out, notice("info", `Files will be saved under ${handle.name}/`));
    }));
    row.append(save, change);
    void savedFolderName().then((name) => {
      if (!name) clear(out, notice("info", "The first save asks you to pick your "
        + "Job Applications folder. It is remembered after that."));
    });
  }
  if (canShareFiles()) {
    const btn = h("button", { class: canSaveToFolder() ? "secondary" : "primary" },
      canSaveToFolder() ? "Share…" : "Share or save to Files");
    btn.addEventListener("click", busy(btn, out, () => share(files, title)));
    row.append(btn);
  }
  if (!canSaveToFolder() && !canShareFiles()) {
    const all = h("button", { class: "primary" }, "Download all");
    all.addEventListener("click", () => files.forEach(download));
    row.append(all);
  }
  return h("div", null, row, out);
}

/**
 * The request id that last built this application folder. History's row is the source:
 * a regenerate moves its `request_id` to the new run, so an old run's result could be stale.
 */
async function latestRequest(gh: GitHub, folder: string, result?: RunResult):
    Promise<string | null> {
  const csv = await gh.getText("applications.csv");
  const name = basename(folder);
  const rows = csv ? parseRecords(csv.text).filter((r) => r.folder === name && r.request_id)
    : [];
  return rows.at(-1)?.request_id ?? (result?.kind === "application" ? result.id : null);
}

function regenerateCard(gh: GitHub, folder: string, result?: RunResult): HTMLElement {
  const note = h("textarea", { id: "regen-note", rows: 3, required: true,
    placeholder: "e.g. lead with the iOS projects; drop the game projects" });
  const provider = h("select", { id: "regen-provider" },
    PROVIDERS.map(([v, l]) => h("option", { value: v }, l)));
  const out = h("div");
  const go = h("button", { class: "primary", type: "submit" }, "Regenerate");
  let previous: string | null = null;

  const form = h("form", { class: "stack" },
    h("p", { class: "hint" }, "Tailors this application again with your note: one "
      + "tailoring call (about $0.05–0.10), because the posting analysis is reused. The "
      + "new PDFs replace these files, and History keeps one row with its status."),
    h("div", { class: "field" }, h("label", { for: note.id }, "Note for the tailoring"), note),
    h("div", { class: "field" }, h("label", { for: provider.id }, "Provider"), provider),
    go, out);
  const card = h("details", { class: "card" },
    h("summary", null, "Regenerate with a note"), form);

  // Loaded when opened, so viewing a folder costs no extra API requests.
  card.addEventListener("toggle", () => {
    if (!card.open || previous) return;
    void latestRequest(gh, folder, result).then(async (id) => {
      previous = id;
      if (!id) {
        clear(out, notice("warn", "This folder has no request id in History, so it cannot "
          + "be regenerated. Start a new application instead."));
        go.disabled = true;
        return;
      }
      const req = await gh.getJson<Partial<ApplicationRequest>>(`requests/${id}.json`);
      if (!note.value && req?.note) note.value = req.note;
    }).catch((e: unknown) => clear(out, notice("error", errorText(e))));
  });

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(go, out, async () => {
      const text = note.value.trim();
      if (!text) throw new Error("Write what should change.");
      const id = previous ?? await latestRequest(gh, folder, result);
      if (!id) throw new Error("This folder cannot be regenerated: no request id in History.");
      const label = basename(folder);
      const req: ApplicationRequest = {
        schema_version: 1, type: "application", id: requestId(label), posting: null,
        company: null, position: null, provider: provider.value || null, model: null,
        note: text, cover_letter: false, regenerates: id,
      };
      await submit(gh, req, `regenerate ${label}`);
      location.hash = `#/run/${req.id}`;
    })();
  });
  return card;
}
