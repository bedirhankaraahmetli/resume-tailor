// A tiny element builder. Text always goes in as text nodes, never as HTML.

type Child = Node | string | number | null | undefined | false;
type Attr = string | number | boolean | null | undefined | ((ev: Event) => void);

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K, attrs?: Record<string, Attr> | null, ...children: (Child | Child[])[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === undefined || v === null || v === false) continue;
    if (typeof v === "function") el.addEventListener(k.replace(/^on/, ""), v);
    else if (k === "class") el.className = String(v);
    else if (v === true) el.setAttribute(k, "");
    else if (k in el && k !== "list" && k !== "form") (el as unknown as Record<string, unknown>)[k] = v;
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

export function clear(el: Element, ...children: (Child | Child[])[]): void {
  el.replaceChildren();
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
}

export function money(usd: number | null | undefined): string {
  return usd === null || usd === undefined ? "–" : `$${usd.toFixed(usd < 0.01 && usd > 0 ? 4 : 2)}`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** A notice line. `kind` sets the colour; the text always says what happened too. */
export function notice(kind: "info" | "ok" | "warn" | "error", ...text: Child[]): HTMLElement {
  return h("div", { class: `notice ${kind}`, role: kind === "error" ? "alert" : "status" },
    ...text);
}

/** Runs an async action from a button, disabling it and showing errors next to it. */
export function busy(button: HTMLButtonElement, out: HTMLElement,
                     action: () => Promise<void>): () => void {
  return () => {
    const label = button.textContent;
    button.disabled = true;
    button.textContent = "Working…";
    clear(out);
    action()
      .catch((e: unknown) => clear(out, notice("error", errorText(e))))
      .finally(() => {
        button.disabled = false;
        button.textContent = label;
      });
  };
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
