// RFC 4180 CSV, enough for applications.csv. Python's csv module writes it with CRLF
// line endings and quotes only fields that need it; appending keeps both conventions.

export const APP_FIELDS = [
  "date", "company", "position", "folder", "provider", "model", "cost_usd", "match_pct",
  "status", "source", "request_id",
] as const;

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let i = 0;
  const src = text.replace(/^﻿/, "");
  while (i < src.length) {
    const c = src[i]!;
    if (quoted) {
      if (c === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
    i++;
  }
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function parseRecords(text: string): Record<string, string>[] {
  const [header, ...rows] = parseCsv(text);
  if (!header) return [];
  return rows
    .filter((r) => r.some((f) => f !== ""))
    .map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
}

function field(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function appendRecord(text: string, record: Record<string, string>): string {
  const eol = text.includes("\r\n") || text === "" ? "\r\n" : "\n";
  let out = text;
  let header: string[];
  if (out.trim() === "") {
    header = [...APP_FIELDS];
    out = header.map(field).join(",") + eol;
  } else {
    header = parseCsv(out)[0] ?? [...APP_FIELDS];
    if (!out.endsWith("\n")) out += eol;
  }
  return out + header.map((h) => field(record[h] ?? "")).join(",") + eol;
}
