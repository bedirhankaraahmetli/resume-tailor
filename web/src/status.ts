// Maps a workflow run and its steps to what the user sees. The step names are a contract
// with .github/workflows/tailor.yml (docs/PLAN.md §2.9): rename them together.

export type Phase =
  | "queued" | "starting" | "analyzing" | "tailoring" | "compiling" | "publishing"
  | "waiting";

export const STEP_PHASE: Record<string, Phase> = {
  "Analyze posting": "analyzing",
  Tailor: "tailoring",
  "Compile and check": "compiling",
  Publish: "publishing",
};

export const PHASE_LABEL: Record<Phase, string> = {
  queued: "Queued",
  starting: "Starting",
  analyzing: "Analyzing the posting",
  tailoring: "Tailoring",
  compiling: "Compiling and checking",
  publishing: "Saving the results",
  waiting: "Waiting for the next run",
};

/** The phases shown as a progress list, in order. */
export const PROGRESS: Phase[] = ["queued", "analyzing", "tailoring", "compiling", "publishing"];

export interface RunInfo {
  status: string; // queued | in_progress | completed | waiting | pending | requested
  conclusion: string | null;
}

export interface StepInfo {
  name: string;
  status: string; // queued | in_progress | completed
  conclusion: string | null;
}

/**
 * The run's phase. `results/<id>.json` is the real source of truth; this only fills the
 * time before it exists. A run cancelled while *pending* never started: GitHub dropped it
 * for a newer one, which builds every pending request, so the request is still coming.
 */
export function phaseOf(run: RunInfo | null, steps: StepInfo[]): Phase {
  if (!run) return "queued";
  if (run.status === "completed") {
    return run.conclusion === "cancelled" && steps.length === 0 ? "waiting" : "publishing";
  }
  if (run.status !== "in_progress") return "queued";
  const current = steps.find((s) => s.status === "in_progress");
  if (current) return STEP_PHASE[current.name] ?? "starting";
  let last: Phase = "starting";
  for (const s of steps) {
    if (s.status === "completed" && STEP_PHASE[s.name]) last = STEP_PHASE[s.name]!;
  }
  // Between steps: the next one is about to start.
  const next: Partial<Record<Phase, Phase>> = {
    analyzing: "tailoring", tailoring: "compiling", compiling: "publishing",
  };
  return next[last] ?? last;
}
