// What this page keeps in the browser, and where.
//
// localStorage (shared by every Pages project of the same GitHub user, so nothing secret
// in plain text): the repo name, the *encrypted* token, the runs this device started,
// and the optional key-expiry dates. sessionStorage (this tab only): the decrypted token.
// Storage can be unavailable (private mode, blocked site data), so every access is guarded.

import { decryptText, encryptText, type Sealed } from "./crypto";
import { GitHub } from "./github";

const PREFIX = "resume-tailor:";
const SETTINGS = `${PREFIX}settings`;
const TOKEN = `${PREFIX}token`;
const RUNS = `${PREFIX}runs`;
const EXPIRY = `${PREFIX}key-expiry`;

function read<T>(storage: Storage | undefined, key: string): T | null {
  try {
    const raw = storage?.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(storage: Storage | undefined, key: string, value: unknown): void {
  try {
    if (value === null) storage?.removeItem(key);
    else storage?.setItem(key, JSON.stringify(value));
  } catch {
    /* storage blocked: the page still works for this session */
  }
}

const local = () => (typeof localStorage === "undefined" ? undefined : localStorage);
const session = () => (typeof sessionStorage === "undefined" ? undefined : sessionStorage);

export interface Settings {
  repo: string;
  token: Sealed;
}

export function settings(): Settings | null {
  return read<Settings>(local(), SETTINGS);
}

export async function saveSettings(repo: string, token: string, passphrase: string) {
  write(local(), SETTINGS, { repo, token: await encryptText(token, passphrase) });
  write(session(), TOKEN, token);
}

export async function unlock(passphrase: string): Promise<void> {
  const s = settings();
  if (!s) throw new Error("No saved settings.");
  write(session(), TOKEN, await decryptText(s.token, passphrase));
}

export function lock(): void {
  write(session(), TOKEN, null);
}

export function forget(): void {
  lock();
  write(local(), SETTINGS, null);
  write(local(), RUNS, null);
}

/** The decrypted token, or null while locked. */
export function sessionToken(): string | null {
  return read<string>(session(), TOKEN);
}

/** The API client, or null while locked. */
export function github(): GitHub | null {
  const s = settings();
  const token = sessionToken();
  return s && token ? new GitHub(token, s.repo) : null;
}

// ---- runs started from this device, so a reload can resume the status view

export interface LocalRun {
  id: string;
  commit: string;
  started: string;
}

export function localRuns(): LocalRun[] {
  return read<LocalRun[]>(local(), RUNS) ?? [];
}

export function rememberRun(run: LocalRun): void {
  write(local(), RUNS, [run, ...localRuns().filter((r) => r.id !== run.id)].slice(0, 30));
}

// ---- API key expiry dates (not secret; the panel cannot read a key's expiry itself)

export function keyExpiry(): Record<string, string> {
  return read<Record<string, string>>(local(), EXPIRY) ?? {};
}

export function setKeyExpiry(name: string, date: string | null): void {
  const all = keyExpiry();
  if (date) all[name] = date;
  else delete all[name];
  write(local(), EXPIRY, all);
}
