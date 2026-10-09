// Mirrors of the Python models the web app reads and writes (src/resume_tailor/models.py,
// docs/PLAN.md §5.3–5.4). Keep them in step.

export interface RunResult {
  id: string;
  status: "done" | "failed";
  kind: "application" | "preset";
  folder: string | null;
  files: Record<string, string>;
  provider: string | null;
  model: string | null;
  cost_usd: number;
  match_pct: number | null;
  notices: string[];
  error: string | null;
  runs?: RunResult[];
}

export interface ApplicationRequest {
  schema_version: 1;
  type: "application";
  id: string;
  /** Null for a regenerate, which reuses the earlier run's posting. */
  posting: { text: string } | null;
  company: string | null;
  position: string | null;
  provider: string | null;
  model: string | null;
  note: string | null;
  cover_letter: boolean;
  /** The request id of the application this run rebuilds in place. */
  regenerates: string | null;
}

export interface PresetRequest {
  schema_version: 1;
  type: "preset";
  id: string;
  presets: string[] | "stale" | "all";
  provider: string | null;
  model: string | null;
}

export interface PresetStatus {
  id: string;
  folder: string;
  position: string;
  status: "up to date" | "outdated" | "never built";
  changed: string[];
  built_at: string | null;
  provider: string | null;
  model: string | null;
  cost_usd: number | null;
  files: Record<string, string>;
}

export interface BaseStatus {
  folder: string;
  status: "up to date" | "outdated" | "never built";
  built_at: string | null;
  files: Record<string, string>;
}

/** A ready-to-use view context: the route's element and whether it is still shown. */
export interface View {
  el: HTMLElement;
  alive: () => boolean;
}
