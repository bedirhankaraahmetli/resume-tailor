// Request ids: `YYYYMMDD-HHMMSS-<slug>` in UTC, like the CLI. The id names the request
// file and results/<id>.json, so it must match the workflow's ID_RE (jobs.py).

const TR: Record<string, string> = {
  ç: "c", Ç: "C", ğ: "g", Ğ: "G", ı: "i", İ: "I", ö: "o", Ö: "O", ş: "s", Ş: "S",
  ü: "u", Ü: "U",
};

export const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

export function slugAscii(text: string): string {
  const ascii = [...text].map((c) => TR[c] ?? c).join("")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "");
  return ascii.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function requestId(label: string | null | undefined, now: Date = new Date()): string {
  const stamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}`
    + `-${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}`;
  const slug = slugAscii(label ?? "").toLowerCase().slice(0, 40).replace(/_+$/, "");
  return `${stamp}-${slug || "posting"}`;
}
