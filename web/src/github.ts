// The only module that talks to the network. The base URL is a constant and the page's
// CSP allows no other origin, so the token can only ever be sent to api.github.com.

import { fromBase64, fromUtf8, toBase64, utf8 } from "./bytes";
import { sealedBox } from "./crypto";
import type { RunInfo, StepInfo } from "./status";

const API = "https://api.github.com";

export class GitHubError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export interface DirEntry {
  name: string;
  path: string;
  type: "file" | "dir" | "symlink" | "submodule";
  sha: string;
}

export interface WorkflowRun extends RunInfo {
  id: number;
  html_url: string;
  created_at: string;
}

export interface Secret {
  name: string;
  updated_at: string;
}

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

function explain(status: number, body: string, what: string): string {
  let msg = "";
  try {
    msg = (JSON.parse(body) as { message?: string }).message ?? "";
  } catch {
    /* not JSON */
  }
  if (status === 401) return "GitHub rejected the token: it is wrong or has expired. Create a new one in Settings.";
  if (status === 403 && /rate limit/i.test(msg)) return "GitHub's API rate limit was hit. Wait a few minutes and try again.";
  if (status === 403) return `The token is not allowed to ${what}. Check its permissions in Settings.`;
  if (status === 404) return `Not found while trying to ${what}. Check the repository name, and that the token can access it.`;
  return `GitHub answered ${status} while trying to ${what}${msg ? `: ${msg}` : ""}.`;
}

export class GitHub {
  constructor(private readonly token: string, readonly repo: string) {}

  private async request(path: string, what: string, init: RequestInit & {
    accept?: string; allow404?: boolean;
  } = {}): Promise<Response | null> {
    const res = await fetch(`${API}${path}`, {
      ...init,
      // Never reuse a cached answer: status and results change while we poll.
      cache: "no-store",
      headers: {
        Accept: init.accept ?? "application/vnd.github+json",
        Authorization: `Bearer ${this.token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
    });
    if (res.status === 404 && init.allow404) return null;
    if (!res.ok) throw new GitHubError(res.status, explain(res.status, await res.text(), what));
    return res;
  }

  private repoPath(rest: string): string {
    return `/repos/${this.repo}${rest}`;
  }

  async checkAccess(): Promise<{ private: boolean; defaultBranch: string; push: boolean }> {
    const res = await this.request(this.repoPath(""), "read the repository");
    const r = (await res!.json()) as { private: boolean; default_branch: string;
      permissions?: { push?: boolean } };
    return { private: r.private, defaultBranch: r.default_branch, push: !!r.permissions?.push };
  }

  /** `ref` reads the file as of a commit, so edits can be based on exactly that commit. */
  async getText(path: string, ref?: string): Promise<{ text: string; sha: string } | null> {
    const at = ref ? `?ref=${encodeURIComponent(ref)}` : "";
    const res = await this.request(this.repoPath(`/contents/${encodePath(path)}${at}`),
      `read ${path}`, { allow404: true });
    if (!res) return null;
    const j = (await res.json()) as { content?: string; sha: string; encoding?: string };
    if (j.content === undefined || j.encoding !== "base64") {
      // Files over 1 MB come without content; fetch them raw.
      const raw = await this.getBytes(path, ref);
      return raw ? { text: fromUtf8(raw), sha: j.sha } : null;
    }
    return { text: fromUtf8(fromBase64(j.content)), sha: j.sha };
  }

  async getJson<T>(path: string): Promise<T | null> {
    const f = await this.getText(path);
    return f ? (JSON.parse(f.text) as T) : null;
  }

  async getBytes(path: string, ref?: string): Promise<Uint8Array | null> {
    const at = ref ? `?ref=${encodeURIComponent(ref)}` : "";
    const res = await this.request(this.repoPath(`/contents/${encodePath(path)}${at}`),
      `download ${path}`, { allow404: true, accept: "application/vnd.github.raw+json" });
    return res ? new Uint8Array(await res.arrayBuffer()) : null;
  }

  async listDir(path: string): Promise<DirEntry[] | null> {
    const res = await this.request(this.repoPath(`/contents/${encodePath(path)}`),
      `list ${path}`, { allow404: true });
    if (!res) return null;
    const j = (await res.json()) as DirEntry[] | DirEntry;
    return Array.isArray(j) ? j : null;
  }

  /** Creates or updates one file in one commit. Returns the commit's sha. */
  async putText(path: string, text: string, message: string, sha?: string): Promise<string> {
    const res = await this.request(this.repoPath(`/contents/${encodePath(path)}`),
      `write ${path}`, {
        method: "PUT",
        body: JSON.stringify({ message, content: toBase64(utf8(text)), ...(sha ? { sha } : {}) }),
      });
    const j = (await res!.json()) as { commit: { sha: string } };
    return j.commit.sha;
  }

  /**
   * Several files in one commit, through the Git Data API (the Contents API writes one file
   * per commit). `edit` gets the files as of the branch head and returns their new text, or
   * null to delete a file. Every file under a `removeUnder` folder is deleted too.
   * The ref moves only as a fast-forward, so a commit that landed in between (the workflow
   * writes too) makes it fail with 422; then it re-reads, re-applies and retries (§2.10).
   */
  async commitFiles(paths: string[], message: string,
                    edit: (files: Map<string, string>) => Map<string, string | null>,
                    removeUnder: string[] = []): Promise<string> {
    const { defaultBranch } = await this.checkAccess();
    const ref = `heads/${defaultBranch.split("/").map(encodeURIComponent).join("/")}`;
    for (let attempt = 1; ; attempt++) {
      const head = await this.json<{ object: { sha: string } }>(`/git/ref/${ref}`,
        "read the branch");
      const commit = await this.json<{ tree: { sha: string } }>(
        `/git/commits/${head.object.sha}`, "read the latest commit");
      const files = new Map<string, string>();
      for (const p of paths) {
        const f = await this.getText(p, head.object.sha);
        if (!f) throw new GitHubError(404, `${p} is missing from the data repo.`);
        files.set(p, f.text);
      }
      const changed = edit(files);
      const entries: object[] = [];
      const deletes = [...changed].filter(([, c]) => c === null).map(([p]) => p);
      if (deletes.length || removeUnder.length) {
        // A deletion must name a path that exists, so look at what the commit holds.
        const all = await this.json<{ tree: { path: string; type: string }[] }>(
          `/git/trees/${commit.tree.sha}?recursive=1`, "list the repository");
        const blobs = all.tree.filter((t) => t.type === "blob").map((t) => t.path);
        const gone = new Set([...deletes.filter((d) => blobs.includes(d)),
          ...blobs.filter((b) => removeUnder.some((dir) => b.startsWith(`${dir}/`)))]);
        for (const path of gone) entries.push({ path, mode: "100644", type: "blob", sha: null });
      }
      for (const [path, content] of changed) {
        if (content !== null) entries.push({ path, mode: "100644", type: "blob", content });
      }
      const tree = await this.json<{ sha: string }>("/git/trees", "write the files", {
        method: "POST",
        body: JSON.stringify({ base_tree: commit.tree.sha, tree: entries }),
      });
      const next = await this.json<{ sha: string }>("/git/commits", "create the commit", {
        method: "POST",
        body: JSON.stringify({ message, tree: tree.sha, parents: [head.object.sha] }),
      });
      try {
        await this.request(this.repoPath(`/git/refs/${ref}`), "move the branch", {
          method: "PATCH", body: JSON.stringify({ sha: next.sha, force: false }),
        });
        return next.sha;
      } catch (e) {
        const conflict = e instanceof GitHubError && (e.status === 409 || e.status === 422);
        if (!conflict || attempt >= 4) throw e;
        await new Promise((r) => setTimeout(r, 800 * attempt));
      }
    }
  }

  private async json<T>(rest: string, what: string, init: RequestInit = {}): Promise<T> {
    const res = await this.request(this.repoPath(rest), what, init);
    return (await res!.json()) as T;
  }

  async runsForCommit(sha: string): Promise<WorkflowRun[]> {
    const res = await this.request(this.repoPath(`/actions/runs?head_sha=${sha}&per_page=10`),
      "read workflow runs");
    return ((await res!.json()) as { workflow_runs: WorkflowRun[] }).workflow_runs;
  }

  async steps(runId: number): Promise<StepInfo[]> {
    const res = await this.request(this.repoPath(`/actions/runs/${runId}/jobs`),
      "read workflow jobs");
    const j = (await res!.json()) as { jobs: { steps?: StepInfo[] }[] };
    return j.jobs.flatMap((job) => job.steps ?? []);
  }

  // ---- Actions secrets (needs the optional "Secrets: read and write" permission)

  async listSecrets(): Promise<Secret[]> {
    const res = await this.request(this.repoPath("/actions/secrets?per_page=100"),
      "list Actions secrets");
    return ((await res!.json()) as { secrets: Secret[] }).secrets;
  }

  /** Encrypts in the browser and stores it. The value is never kept anywhere here. */
  async putSecret(name: string, value: string): Promise<void> {
    const res = await this.request(this.repoPath("/actions/secrets/public-key"),
      "read the repository's public key for secrets");
    const key = (await res!.json()) as { key_id: string; key: string };
    const encrypted = toBase64(sealedBox(utf8(value), fromBase64(key.key)));
    await this.request(this.repoPath(`/actions/secrets/${encodeURIComponent(name)}`),
      `store the secret ${name}`, {
        method: "PUT",
        body: JSON.stringify({ encrypted_value: encrypted, key_id: key.key_id }),
      });
  }
}
