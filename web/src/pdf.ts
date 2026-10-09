// pdf.js, bundled (never from a CDN) and loaded only when a PDF is first needed.

import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

type PdfJs = typeof import("pdfjs-dist");
let lib: Promise<PdfJs> | null = null;

function pdfjs(): Promise<PdfJs> {
  lib ??= import("pdfjs-dist").then((m) => {
    m.GlobalWorkerOptions.workerSrc = workerUrl;
    return m;
  });
  return lib;
}

async function open(data: Uint8Array) {
  const m = await pdfjs();
  // pdf.js takes ownership of the buffer: pass a copy so the caller can still use it.
  // (pdf.js 6 no longer compiles fonts with eval, so the strict CSP needs no exception.)
  const task = m.getDocument({ data: data.slice() });
  return { task, doc: await task.promise };
}

/** The text of a posting PDF, page by page. */
export async function pdfText(data: Uint8Array): Promise<string> {
  const { task, doc } = await open(data);
  const pages: string[] = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const content = await (await doc.getPage(i)).getTextContent();
    let line = "";
    const lines: string[] = [];
    for (const item of content.items) {
      if (!("str" in item)) continue;
      line += item.str;
      if (item.hasEOL) {
        lines.push(line);
        line = "";
      }
    }
    if (line) lines.push(line);
    pages.push(lines.join("\n"));
  }
  await task.destroy();
  return pages.join("\n\n").trim();
}

/** Renders page 1 into a canvas sized to `cssWidth`, sharp on high-DPI screens. */
export async function renderFirstPage(data: Uint8Array, cssWidth: number): Promise<HTMLCanvasElement> {
  const { task, doc } = await open(data);
  const page = await doc.getPage(1);
  const base = page.getViewport({ scale: 1 });
  const ratio = Math.min(window.devicePixelRatio || 1, 3);
  const viewport = page.getViewport({ scale: (cssWidth / base.width) * ratio });
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  canvas.style.width = `${cssWidth}px`;
  canvas.style.aspectRatio = `${viewport.width} / ${viewport.height}`;
  await page.render({ canvas, viewport }).promise;
  await task.destroy();
  return canvas;
}
