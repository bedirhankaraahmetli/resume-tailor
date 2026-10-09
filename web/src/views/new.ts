// New application: posting (text or file), optional overrides, submit.

import { busy, clear, h, notice } from "../dom";
import type { GitHub } from "../github";
import { requestId } from "../ids";
import { pdfText } from "../pdf";
import { submit } from "../requests";
import type { ApplicationRequest, LetterChoice, View } from "../types";

export const PROVIDERS: [string, string][] = [
  ["", "Default order (Claude API first)"],
  ["anthropic", "Claude API (prepaid credits)"],
  ["claude-code", "Claude Code (Pro subscription)"],
  ["gemini", "Gemini (free tier)"],
];

const LETTERS: [string, string][] = [
  ["", "No cover letter"],
  ["en", "English"],
  ["tr", "Türkçe"],
  ["both", "Both (English + Türkçe)"],
];

/** The cover letter choice; no letter is the default. */
export function letterSelect(id: string): HTMLSelectElement {
  return h("select", { id }, LETTERS.map(([v, l]) => h("option", { value: v }, l)));
}

export function letterChoice(select: HTMLSelectElement): LetterChoice | null {
  return (select.value || null) as LetterChoice | null;
}

export const LETTER_HINT = "Written from your inventory only, checked like the resume, on "
  + "your resume's letterhead. Adds about $0.03–0.05; one language saves about $0.01.";

function field(label: string, input: HTMLElement, hint?: string): HTMLElement {
  const id = input.id;
  return h("div", { class: "field" },
    h("label", { for: id }, label), input, hint ? h("p", { class: "hint" }, hint) : null);
}

export function showNew(view: View, gh: GitHub): void {
  const posting = h("textarea", { id: "posting", rows: 12, required: true,
    placeholder: "Paste the job posting here" });
  const file = h("input", { id: "posting-file", type: "file",
    accept: ".txt,.md,.pdf,text/plain,application/pdf" });
  const company = h("input", { id: "company", autocomplete: "off" });
  const position = h("input", { id: "position", autocomplete: "off" });
  const provider = h("select", { id: "provider" },
    PROVIDERS.map(([v, l]) => h("option", { value: v }, l)));
  const note = h("input", { id: "note", autocomplete: "off", placeholder: "e.g. emphasize iOS" });
  const cover = letterSelect("cover");
  const fileOut = h("div");
  const out = h("div");

  file.addEventListener("change", () => {
    const f = file.files?.[0];
    if (!f) return;
    clear(fileOut, notice("info", `Reading ${f.name}…`));
    (async () => {
      const bytes = new Uint8Array(await f.arrayBuffer());
      const isPdf = f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
      const text = isPdf ? await pdfText(bytes) : new TextDecoder().decode(bytes);
      if (!text.trim()) throw new Error("No text found in the file. A scanned PDF has no "
        + "text layer: paste the posting instead.");
      posting.value = text;
      clear(fileOut, notice("ok", `Loaded ${f.name}. Check the text below before submitting.`));
    })().catch((e: unknown) => clear(fileOut, notice("error", String(e instanceof Error
      ? e.message : e))));
  });

  const go = h("button", { class: "primary", type: "submit" }, "Tailor my resume");
  const form = h("form", { class: "stack", novalidate: true },
    field("Job posting", posting),
    field("…or load it from a file", file, "A .txt or .pdf file. The text is extracted here, "
      + "in your browser."),
    fileOut,
    field("Cover letter", cover, LETTER_HINT),
    h("details", { class: "card" }, h("summary", null, "Options"),
      field("Company (optional)", company, "Leave empty to take it from the posting."),
      field("Position (optional)", position, "Leave empty to use the title in the posting, "
        + "word for word."),
      field("Provider", provider),
      field("Note for the tailoring (optional)", note)),
    h("p", { class: "hint" }, "A run takes about a minute and costs roughly $0.05–0.10 on "
      + "the Claude API. The exact cost is shown with the result."),
    go, out);

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(go, out, async () => {
      const text = posting.value.trim();
      if (text.length < 50) throw new Error("Paste the whole job posting first.");
      const label = company.value.trim() || position.value.trim() || null;
      const req: ApplicationRequest = {
        schema_version: 1, type: "application", id: requestId(label),
        posting: { text },
        company: company.value.trim() || null,
        position: position.value.trim() || null,
        provider: provider.value || null, model: null,
        note: note.value.trim() || null, cover_letter: letterChoice(cover), regenerates: null,
      };
      await submit(gh, req, label ?? "new application");
      location.hash = `#/run/${req.id}`;
    })();
  });

  clear(view.el, h("h1", null, "New application"), form);
}
