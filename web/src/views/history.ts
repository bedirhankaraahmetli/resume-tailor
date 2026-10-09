// History: applications.csv, newest first, each row linking to its files.

import { parseRecords, setField } from "../csv";
import { clear, errorText, h, notice } from "../dom";
import { GitHubError, type GitHub } from "../github";
import type { View } from "../types";

/** The repo folder holding a row's files. Preset-based rows point at the preset. */
export function rowFolder(row: Record<string, string>): string | null {
  const folder = row.folder ?? "";
  if (!folder) return null;
  if (folder.startsWith("_Presets/")) return `presets/${folder.slice("_Presets/".length)}`;
  if (folder === "_Base") return "base-pdf";
  return `applications/${folder}`;
}

export async function showHistory(view: View, gh: GitHub): Promise<void> {
  clear(view.el, h("h1", null, "History"), notice("info", "Loading…"));
  const csv = await gh.getText("applications.csv");
  if (!view.alive()) return;
  // Each row keeps its position in the file, which the status editor needs.
  const rows = csv ? parseRecords(csv.text).map((r, i): Record<string, string> => ({ ...r, __i: String(i) })).reverse()
    : [];
  if (!rows.length) {
    clear(view.el, h("h1", null, "History"), notice("info", "No applications yet."));
    return;
  }
  const total = rows.reduce((n, r) => n + (Number.parseFloat(r.cost_usd ?? "") || 0), 0);
  clear(view.el,
    h("h1", null, "History"),
    h("p", { class: "muted" }, `${rows.length} application(s) · total cost $${total.toFixed(2)}`),
    h("ul", { class: "cards history" }, rows.map((r) => {
      const folder = rowFolder(r);
      const title = `${r.company || "–"} – ${r.position || "–"}`;
      return h("li", { class: "card" },
        h("div", { class: "card-head" },
          folder
            ? h("a", { href: `#/folder/${encodeURIComponent(folder)}` }, title)
            : h("strong", null, title),
          statusPicker(gh, r)),
        h("p", { class: "muted small" }, [
          r.date,
          r.match_pct ? `match ${r.match_pct}%` : null,
          r.cost_usd ? `$${r.cost_usd}` : null,
          r.source === "base" ? "base resume"
            : r.source?.startsWith("preset:") ? `preset ${r.source.slice(7)}` : r.provider,
        ].filter(Boolean).join(" · ")));
    })));
}

// "generated" is what the workflow writes for a tailored run nobody has applied with yet.
export const STATUSES = ["generated", "applied", "interview", "offer", "rejected"] as const;

/** Changes one row's status and commits applications.csv, retrying on a conflict (§2.10). */
function statusPicker(gh: GitHub, row: Record<string, string>): HTMLElement {
  const { __i, ...original } = row;
  const current = original.status ?? "";
  const options = STATUSES.includes(current as (typeof STATUSES)[number]) || !current
    ? [...STATUSES] : [current, ...STATUSES];
  const select = h("select", { class: "status", "aria-label":
    `Status of ${original.company || "this application"}` },
    options.map((s) => h("option", { value: s, selected: s === current }, s)));
  const out = h("span", { class: "small", role: "status" });
  let saved = current;
  select.addEventListener("change", () => {
    const value = select.value;
    select.disabled = true;
    out.textContent = "Saving…";
    (async () => {
      for (let attempt = 1; ; attempt++) {
        const csv = await gh.getText("applications.csv");
        if (!csv) throw new Error("applications.csv is missing.");
        try {
          await gh.putText("applications.csv",
            setField(csv.text, Number(__i), { ...original, status: saved }, "status", value),
            `status: ${original.company} - ${original.position} → ${value}`, csv.sha);
          return;
        } catch (e) {
          const conflict = e instanceof GitHubError && (e.status === 409 || e.status === 422);
          if (!conflict || attempt >= 4) throw e;
          await new Promise((r) => setTimeout(r, 800 * attempt));
        }
      }
    })().then(() => {
      saved = value;
      out.textContent = "✓ Saved";
    }).catch((e: unknown) => {
      select.value = saved;
      out.textContent = `Not saved: ${errorText(e)}`;
    }).finally(() => { select.disabled = false; });
  });
  return h("span", { class: "status-edit" }, select, out);
}
