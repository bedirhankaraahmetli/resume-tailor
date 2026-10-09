// Shows one output folder of the data repo: both PDFs (preview, download, share, save to
// folder) and the match report. Used for a finished run, a History row and a preset.

import { busy, clear, errorText, h, money, notice } from "../dom";
import type { GitHub } from "../github";
import { renderMarkdown } from "../markdown";
import { renderFirstPage } from "../pdf";
import {
  canSaveToFolder, canShareFiles, chooseFolder, download, saveToFolder, savedFolderName, share,
  type OutFile,
} from "../save";
import type { RunResult, View } from "../types";

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

/** `applications/X` → `X`; `presets/X` → `_Presets/X` (PROMPT.md §9). */
export function localSubfolder(folder: string): string[] {
  const [top, ...rest] = folder.split("/");
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
  const title = basename(folder);
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
      "Share or save to Files");
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
