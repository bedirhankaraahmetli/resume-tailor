// Writing request files: one commit each, which starts the data repo's workflow.

import type { GitHub } from "./github";
import { rememberRun } from "./store";
import type { ApplicationRequest, PresetRequest } from "./types";

export async function submit(gh: GitHub, req: ApplicationRequest | PresetRequest,
                             label: string): Promise<string> {
  const text = `${JSON.stringify(req, null, 2)}\n`;
  const commit = await gh.putText(`requests/${req.id}.json`, text, `request: ${label}`);
  rememberRun({ id: req.id, commit, started: new Date().toISOString() });
  return commit;
}
