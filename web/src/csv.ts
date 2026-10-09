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

/** Where each record (header included) starts and ends in the text, line break excluded. */
function recordSpans(text: string): [number, number][] {
  const spans: [number, number][] = [];
  let start = 0;
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') quoted = !quoted;
    else if (!quoted && (c === "\n" || c === "\r")) {
      spans.push([start, i]);
      if (c === "\r" && text[i + 1] === "\n") i++;
      start = i + 1;
    }
  }
  if (start < text.length) spans.push([start, text.length]);
  return spans;
}

/** The data row matching `original`, preferring position `index`; -1 if it is gone. */
function findRecord(rows: string[][], index: number, original: Record<string, string>): number {
  const header = rows[0] ?? [];
  const same = (r: string[] | undefined): boolean =>
    !!r && header.every((h, i) => (r[i] ?? "") === (original[h] ?? ""));
  if (same(rows[index + 1])) return index + 1;
  return rows.findIndex((r, i) => i > 0 && same(r));
}

/** Removes one record, line break included, and leaves every other byte alone. */
export function removeRecord(text: string, index: number,
                             original: Record<string, string>): string {
  const src = text.replace(/^\uFEFF/, "");
  const bom = text.length - src.length;
  const at = findRecord(parseCsv(src), index, original);
  if (at < 1) throw new Error("That application changed in the meantime. Reload History.");
  const [a] = recordSpans(src)[at]!;
  const next = recordSpans(src)[at + 1];
  const end = next ? next[0] : src.length;
  return text.slice(0, bom + a) + text.slice(bom + end);
}

/**
 * Sets one field of one record and leaves every other byte alone. The record is found by
 * its full content, preferring `index` (its position among the data rows), so a row the
 * workflow appended in the meantime cannot make us edit the wrong one.
 */
export function setField(text: string, index: number, original: Record<string, string>,
                         name: string, value: string): string {
  const src = text.replace(/^﻿/, "");
  const bom = text.length - src.length;
  const spans = recordSpans(src);
  const rows = parseCsv(src);
  const header = rows[0] ?? [];
  const col = header.indexOf(name);
  if (col < 0) throw new Error(`applications.csv has no “${name}” column.`);
  const same = (r: string[] | undefined): boolean =>
    !!r && header.every((h, i) => (r[i] ?? "") === (original[h] ?? ""));
  let at = same(rows[index + 1]) ? index + 1 : -1;
  if (at < 0) at = rows.findIndex((r, i) => i > 0 && same(r));
  if (at < 0) throw new Error("That application changed in the meantime. Reload History.");
  const cells = header.map((_, i) => rows[at]![i] ?? "");
  cells[col] = value;
  const [a, b] = spans[at]!;
  return text.slice(0, bom + a) + cells.map(field).join(",") + text.slice(bom + b);
}
