// A small Markdown renderer for our own match reports: headings, lists, tables, bold,
// inline code and paragraphs. Everything is HTML-escaped *before* any markup is added,
// so the output only ever contains the tags created here.

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function inline(s: string): string {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

const SEPARATOR = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/;

export function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let para: string[] = [];
  let list: string[] = [];

  const flush = () => {
    if (para.length) out.push(`<p>${para.map(inline).join(" ")}</p>`);
    if (list.length) out.push(`<ul>${list.map((l) => `<li>${inline(l)}</li>`).join("")}</ul>`);
    para = [];
    list = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      // The page already has an <h1>; report headings start one level lower.
      const level = Math.min(heading[1]!.length + 1, 6);
      out.push(`<h${level}>${inline(heading[2]!)}</h${level}>`);
    } else if (/^\s*[-*]\s+/.test(line)) {
      if (para.length) flush();
      list.push(line.replace(/^\s*[-*]\s+/, ""));
    } else if (line.trim().startsWith("|") && SEPARATOR.test(lines[i + 1]?.trim() ?? "")) {
      flush();
      const head = cells(line);
      const align = cells(lines[i + 1]!).map((c) => (c.endsWith(":") ? "right" : ""));
      i += 2;
      const body: string[][] = [];
      while (i < lines.length && lines[i]!.trim().startsWith("|")) body.push(cells(lines[i++]!));
      i--;
      const td = (tag: string, c: string, j: number) =>
        `<${tag}${align[j] ? ` class="num"` : ""}>${inline(c)}</${tag}>`;
      out.push(
        `<div class="table-wrap"><table><thead><tr>${head.map((c, j) => td("th", c, j)).join("")}`
          + `</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c, j) => td("td", c, j)).join("")}</tr>`).join("")}`
          + "</tbody></table></div>",
      );
    } else if (line.trim() === "") {
      flush();
    } else {
      if (list.length) flush();
      para.push(line.trim());
    }
  }
  flush();
  return out.join("\n");
}
