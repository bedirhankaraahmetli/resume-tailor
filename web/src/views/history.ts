// History: applications.csv, newest first, each row linking to its files.

import { parseRecords } from "../csv";
import { clear, h, notice } from "../dom";
import type { GitHub } from "../github";
import type { View } from "../types";

/** The repo folder holding a row's files. Preset-based rows point at the preset. */
export function rowFolder(row: Record<string, string>): string | null {
  const folder = row.folder ?? "";
  if (!folder) return null;
  if (folder.startsWith("_Presets/")) return `presets/${folder.slice("_Presets/".length)}`;
  return `applications/${folder}`;
}

export async function showHistory(view: View, gh: GitHub): Promise<void> {
  clear(view.el, h("h1", null, "History"), notice("info", "Loading…"));
  const csv = await gh.getText("applications.csv");
  if (!view.alive()) return;
  const rows = csv ? parseRecords(csv.text).reverse() : [];
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
          h("span", { class: "badge muted" }, r.status || "–")),
        h("p", { class: "muted small" }, [
          r.date,
          r.match_pct ? `match ${r.match_pct}%` : null,
          r.cost_usd ? `$${r.cost_usd}` : null,
          r.source?.startsWith("preset:") ? `preset ${r.source.slice(7)}` : r.provider,
        ].filter(Boolean).join(" · ")));
    })));
}
