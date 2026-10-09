// Quick apply: the ready-made preset pairs, their status, and actions on them.

import { appendRecord } from "../csv";
import { busy, clear, h, money, notice, shortDate } from "../dom";
import { GitHubError, type GitHub } from "../github";
import { requestId } from "../ids";
import { submit } from "../requests";
import type { BaseStatus, PresetRequest, PresetStatus, View } from "../types";

const BADGE: Record<PresetStatus["status"], [string, string]> = {
  "up to date": ["ok", "✓ Up to date"],
  outdated: ["warn", "! Outdated"],
  "never built": ["muted", "– Never built"],
};

export async function showPresets(view: View, gh: GitHub): Promise<void> {
  clear(view.el, h("h1", null, "Quick apply"), notice("info", "Loading presets…"));
  const report = await gh.getJson<{ base?: BaseStatus; presets: PresetStatus[] }>(
    "presets/status.json");
  if (!view.alive()) return;
  if (!report) {
    clear(view.el, h("h1", null, "Quick apply"), notice("info", "No preset status yet. "
      + "It is written by the next workflow run, or when base/, the inventory or "
      + "presets.yml change."));
    return;
  }
  const stale = report.presets.filter((p) => p.status !== "up to date");
  const out = h("div");
  const rebuildAll = h("button", { class: "secondary", disabled: stale.length === 0 },
    stale.length ? `Rebuild ${stale.length} outdated` : "All presets are up to date");
  rebuildAll.addEventListener("click", busy(rebuildAll, out, async () => {
    if (!confirm(`Rebuild ${stale.length} preset(s)? About $0.04 each on the Claude API.`)) return;
    await rebuild(gh, "stale", "outdated presets");
  }));

  clear(view.el,
    h("h1", null, "Quick apply"),
    h("p", { class: "muted" }, "Ready-made resumes per role family. Use one when a posting "
      + "fits a preset well, and log the application here."),
    h("div", { class: "row" }, rebuildAll), out,
    h("ul", { class: "cards" },
      report.base ? baseCard(gh, report.base) : null,
      report.presets.map((p) => presetCard(gh, p))));
}

async function rebuild(gh: GitHub, presets: string[] | "stale", label: string) {
  const req: PresetRequest = { schema_version: 1, type: "preset",
    id: requestId(`preset ${label}`), presets, provider: null, model: null };
  await submit(gh, req, `rebuild ${label}`);
  location.hash = `#/run/${req.id}`;
}

/** The untailored base resumes. Rebuilt by the workflow whenever base/ changes. */
function baseCard(gh: GitHub, b: BaseStatus): HTMLElement {
  const out = h("div");
  const built = b.status !== "never built";
  const log = h("button", { class: "secondary", disabled: !built }, "Log this application");
  log.addEventListener("click", () => clear(out, logForm(gh, {
    id: "base", label: "base", folder: "_Base", position: "", provider: "", model: "",
  }, out)));
  return h("li", { class: "card" },
    h("div", { class: "card-head" },
      h("h2", null, "Base resume"),
      h("span", { class: `badge ${built ? (b.status === "up to date" ? "ok" : "warn") : "muted"}` },
        b.status === "up to date" ? "✓ Matches base/" : b.status === "outdated"
          ? "! Rebuilding soon" : "– Not built yet")),
    h("p", { class: "muted small" }, built
      ? `Your resumes exactly as written, not tailored · built ${shortDate(b.built_at)}`
      : "Built by the next workflow run, at no cost."),
    h("div", { class: "row" },
      built ? h("a", { class: "button primary", href: `#/folder/${encodeURIComponent(b.folder)}` },
        "Open") : null,
      log),
    out);
}

function presetCard(gh: GitHub, p: PresetStatus): HTMLElement {
  const [cls, text] = BADGE[p.status];
  const out = h("div");
  const open = h("a", { class: "button primary", href: `#/folder/${encodeURIComponent(
    `presets/${p.folder}`)}` }, "Open");
  const rebuildBtn = h("button", { class: "secondary" }, p.status === "never built"
    ? "Build" : "Rebuild");
  rebuildBtn.addEventListener("click", busy(rebuildBtn, out, async () => {
    if (!confirm(`Rebuild ${p.position}? About $0.04 on the Claude API.`)) return;
    await rebuild(gh, [p.id], p.id);
  }));
  const log = h("button", { class: "secondary", disabled: p.status === "never built" },
    "Log this application");
  log.addEventListener("click", () => clear(out, logForm(gh, {
    id: p.id, label: `preset ${p.id}`, folder: `_Presets/${p.folder}`, position: p.position,
    provider: p.provider ?? "", model: p.model ?? "",
  }, out)));

  return h("li", { class: "card" },
    h("div", { class: "card-head" },
      h("h2", null, p.position),
      h("span", { class: `badge ${cls}` }, text)),
    h("p", { class: "muted small" }, `${p.folder} · built ${shortDate(p.built_at)} · `
      + `${money(p.cost_usd)}${p.model ? ` · ${p.model}` : ""}`),
    p.status === "outdated" && p.changed.length
      ? h("p", { class: "small" }, `Changed since: ${p.changed.join(", ")}`) : null,
    h("div", { class: "row" }, p.status === "never built" ? null : open, rebuildBtn, log),
    out);
}

interface LogTarget {
  id: string; // used in element ids and the CSV source column
  label: string; // for the commit message
  folder: string; // the CSV folder column: where History links to
  position: string; // pre-filled
  provider: string;
  model: string;
}

function logForm(gh: GitHub, p: LogTarget, out: HTMLElement): HTMLElement {
  const company = h("input", { id: `co-${p.id}`, required: true, autocomplete: "off" });
  const position = h("input", { id: `po-${p.id}`, required: true, autocomplete: "off",
    value: p.position });
  const save = h("button", { class: "primary", type: "submit" }, "Add to History");
  const msg = h("div");
  const form = h("form", { class: "stack card inset" },
    h("div", { class: "field" }, h("label", { for: company.id }, "Company"), company),
    h("div", { class: "field" }, h("label", { for: position.id }, "Position"), position),
    h("div", { class: "row" }, save,
      h("button", { type: "button", class: "link", onclick: () => clear(out) }, "Cancel")),
    msg);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(save, msg, async () => {
      const c = company.value.trim();
      const pos = position.value.trim();
      if (!c || !pos) throw new Error("Enter the company and the position.");
      await appendApplication(gh, {
        date: new Date().toISOString().slice(0, 10), company: c, position: pos,
        folder: p.folder, provider: p.provider, model: p.model,
        // A preset's cost was already counted when it was built; the base costs nothing.
        cost_usd: "0.0000", match_pct: "", status: "applied",
        source: p.id === "base" ? "base" : `preset:${p.id}`, request_id: "",
      }, `log: ${c} - ${pos} (${p.label})`);
      clear(out, notice("ok", `Logged ${c} – ${pos}. It is in History now.`));
    })();
  });
  return form;
}

/**
 * Appends one row with the file's sha, so a concurrent write (the workflow adds rows too)
 * fails with 409 instead of being overwritten. Then: re-read, re-apply, retry (§2.10).
 */
export async function appendApplication(gh: GitHub, row: Record<string, string>,
                                        message: string): Promise<void> {
  for (let attempt = 1; ; attempt++) {
    const current = await gh.getText("applications.csv");
    try {
      await gh.putText("applications.csv", appendRecord(current?.text ?? "", row), message,
        current?.sha);
      return;
    } catch (e) {
      const conflict = e instanceof GitHubError && (e.status === 409 || e.status === 422);
      if (!conflict || attempt >= 4) throw e;
      await new Promise((r) => setTimeout(r, 800 * attempt));
    }
  }
}
