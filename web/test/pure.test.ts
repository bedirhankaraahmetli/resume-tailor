import { describe, expect, it } from "vitest";
import { appendRecord, parseCsv, parseRecords } from "../src/csv";
import { ID_RE, requestId, slugAscii } from "../src/ids";
import { escapeHtml, renderMarkdown } from "../src/markdown";
import { phaseOf } from "../src/status";
import { fromBase64, fromUtf8, toBase64, utf8 } from "../src/bytes";

describe("ids", () => {
  it("transliterates Turkish and matches the workflow's id rule", () => {
    expect(slugAscii("Örnek Teknoloji A.Ş.")).toBe("Ornek_Teknoloji_A_S");
    expect(slugAscii("İstanbul Iğdır")).toBe("Istanbul_Igdir");
    const id = requestId("Örnek Teknoloji A.Ş.", new Date(Date.UTC(2026, 9, 9, 14, 5, 7)));
    expect(id).toBe("20261009-140507-ornek_teknoloji_a_s");
    expect(ID_RE.test(id)).toBe(true);
  });

  it("falls back to 'posting' and never ends in a separator", () => {
    expect(requestId(null, new Date(0))).toBe("19700101-000000-posting");
    expect(requestId("!!!", new Date(0))).toBe("19700101-000000-posting");
    expect(requestId("a".repeat(39) + " b", new Date(0)).endsWith("_")).toBe(false);
  });
});

describe("csv", () => {
  const base = "date,company,position\r\n2026-10-09,\"ABC, Inc\",\"Say \"\"hi\"\"\"\r\n";

  it("parses quoted fields, commas and doubled quotes", () => {
    expect(parseCsv(base)).toEqual([
      ["date", "company", "position"],
      ["2026-10-09", "ABC, Inc", 'Say "hi"'],
    ]);
    expect(parseRecords(base)[0]).toEqual({ date: "2026-10-09", company: "ABC, Inc",
      position: 'Say "hi"' });
  });

  it("appends in the file's own column order and line ending", () => {
    const out = appendRecord(base, { position: "Veri Bilimci", company: "Örnek A.Ş.",
      date: "2026-10-10", ignored: "x" });
    expect(out).toBe(base + "2026-10-10,Örnek A.Ş.,Veri Bilimci\r\n");
    expect(parseRecords(out)).toHaveLength(2);
  });

  it("creates the header for an empty file and repairs a missing final newline", () => {
    const fresh = appendRecord("", { date: "d", company: "c" });
    expect(fresh.split("\r\n")[0]).toBe(
      "date,company,position,folder,provider,model,cost_usd,match_pct,status,source,request_id");
    expect(appendRecord("a,b\nx,y", { a: "1", b: "2" })).toBe("a,b\nx,y\n1,2\n");
  });
});

describe("markdown", () => {
  it("escapes HTML before adding markup", () => {
    const html = renderMarkdown("# T <script>\n\nA **<img src=x onerror=alert(1)>** `<b>`");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("<strong>&lt;img src=x onerror=alert(1)&gt;</strong>");
    expect(html).toContain("<code>&lt;b&gt;</code>");
    expect(escapeHtml(`"'&`)).toBe("&quot;&#39;&amp;");
  });

  it("renders the report's headings, lists and tables", () => {
    const md = "## Keyword match\n\n- Python\n- SQL\n\n| Call | Cost |\n|---|---:|\n| 1 | $0.01 |\n\nTotal **$0.01**";
    const html = renderMarkdown(md);
    expect(html).toContain("<h3>Keyword match</h3>");
    expect(html).toContain("<ul><li>Python</li><li>SQL</li></ul>");
    expect(html).toContain('<td class="num">$0.01</td>');
    expect(html).toContain("<p>Total <strong>$0.01</strong></p>");
  });
});

describe("status", () => {
  const step = (name: string, status: string) => ({ name, status, conclusion: null });

  it("follows the named steps", () => {
    expect(phaseOf(null, [])).toBe("queued");
    expect(phaseOf({ status: "queued", conclusion: null }, [])).toBe("queued");
    expect(phaseOf({ status: "pending", conclusion: null }, [])).toBe("queued");
    const run = { status: "in_progress", conclusion: null };
    expect(phaseOf(run, [step("Set up TinyTeX", "in_progress")])).toBe("starting");
    expect(phaseOf(run, [step("Analyze posting", "in_progress")])).toBe("analyzing");
    expect(phaseOf(run, [step("Analyze posting", "completed"), step("Tailor", "queued")]))
      .toBe("tailoring");
    expect(phaseOf(run, [step("Tailor", "completed"), step("Compile and check", "in_progress")]))
      .toBe("compiling");
  });

  it("treats a run cancelled while pending as still coming", () => {
    expect(phaseOf({ status: "completed", conclusion: "cancelled" }, [])).toBe("waiting");
    expect(phaseOf({ status: "completed", conclusion: "success" }, [])).toBe("publishing");
  });
});

describe("bytes", () => {
  it("round-trips UTF-8 through base64", () => {
    const s = "Özgeçmiş — İş başvurusu ✓";
    expect(fromUtf8(fromBase64(toBase64(utf8(s))))).toBe(s);
  });
});
