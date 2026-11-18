import { REPORT_STYLE_HASH } from "virtual:report-style";

/** What runs inside the report frame. The frame is sandboxed without `allow-same-origin`
 * (spec §10.3, M7), so the page cannot reach into it and nothing in it can reach the page; this
 * bridge is the one channel. The frame posts the claim a reader clicked and says when it is
 * ready; the page posts the claim to highlight. */

export type FrameToHost = { type: "corelata:ready" } | { type: "corelata:select"; claim: string };
export type HostToFrame =
  | { type: "corelata:highlight"; claim: string | null; scroll: boolean }
  | { type: "corelata:theme"; theme: "light" | "dark" };

/** The bridge's own stylesheet, bound to the frame's nonce: the claim highlight, and the two
 * classes that set the report's colour scheme to the app's theme (M18 spec §5.5, R-M18-2). The
 * report's stylesheet says `color-scheme: light dark` on `:root`; a class on the frame's root is
 * more specific, so the app's choice wins over the computer's. */
export const HIGHLIGHT_CSS =
  ".corelata-highlight { background: #fff3b0; color: #1a1a1a; outline: 2px solid #e0a800; outline-offset: 2px; }" +
  " :root.corelata-theme-light { color-scheme: light; } :root.corelata-theme-dark { color-scheme: dark; }";

/** Installed inside the frame. Self-contained on purpose: `bridgeScript()` serialises it with
 * `Function.prototype.toString`, so its body may not reference anything outside itself. */
export function installFrameBridge(
  doc: Document,
  post: (message: FrameToHost) => void,
  listen: (handler: (message: HostToFrame) => void) => void,
  css: string,
  nonce: string,
  theme = "",
): void {
  const setTheme = (next: string) => {
    if (next !== "light" && next !== "dark") return;
    doc.documentElement.classList.remove("corelata-theme-light", "corelata-theme-dark");
    doc.documentElement.classList.add(`corelata-theme-${next}`);
  };
  setTheme(theme); // the theme the page had when it built the frame: no flash of the other one
  const style = doc.createElement("style");
  if (nonce) style.setAttribute("nonce", nonce); // the frame's policy allows this style by nonce
  style.textContent = css;
  doc.head.appendChild(style);
  doc.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    if (target?.closest("a[href]")) event.preventDefault(); // a report's links navigate nothing
    const cited = target?.closest("[data-claim-ids]");
    const first = (cited?.getAttribute("data-claim-ids") ?? "").split(/\s+/).filter(Boolean)[0];
    if (first) post({ type: "corelata:select", claim: first });
  });
  listen((message) => {
    if (message && message.type === "corelata:theme") return setTheme(message.theme);
    if (!message || message.type !== "corelata:highlight") return;
    for (const el of doc.querySelectorAll(".corelata-highlight"))
      el.classList.remove("corelata-highlight");
    if (!message.claim) return;
    const marked = doc.querySelectorAll(`[data-claim-ids~="${CSS.escape(message.claim)}"]`);
    for (const el of marked) el.classList.add("corelata-highlight");
    if (message.scroll) marked[0]?.scrollIntoView?.({ block: "center" });
  });
  post({ type: "corelata:ready" });
}

/** The frame's own policy (R-M9-6, R-M14-2): nothing loads from anywhere; the bridge's script
 * and its highlight style run by nonce; the report's stylesheet is allowed by its hash, computed
 * at build time from the engine's file; no other inline script or style runs. A site proxy's
 * policy is inherited on top of this one (docs/operator-guide.md, section 6). */
export const FRAME_CSP = (nonce: string) =>
  `default-src 'none'; script-src 'nonce-${nonce}'; style-src '${REPORT_STYLE_HASH}' 'nonce-${nonce}'; img-src data:; connect-src 'none'`;

export function frameNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function cspMeta(nonce: string): string {
  return `<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP(nonce)}">`;
}

/** The `<script>` that installs the bridge: it talks to `parent` and trusts only `parent`.
 * `theme` is the app's theme when the page builds the frame (R-M18-10). */
export function bridgeScript(nonce?: string, theme?: "light" | "dark"): string {
  const attr = nonce ? ` nonce="${nonce}"` : "";
  const initial = theme ? `, ${JSON.stringify(theme)}` : "";
  return (
    `<script${attr}>(${installFrameBridge.toString()})(document,` +
    ' function (m) { parent.postMessage(m, "*"); },' +
    ' function (h) { addEventListener("message", function (e) { if (e.source === parent) h(e.data); }); },' +
    ` ${JSON.stringify(HIGHLIGHT_CSS)}, ${JSON.stringify(nonce ?? "")}${initial});</script>`
  );
}

/** The built theme's class on the report's `<html>` start tag, so the first paint is already in
 * that theme (the bridge script runs only at the end of `<body>`). A `class` attribute the tag
 * has keeps its classes; a document without the tag is left as it is, and the bridge sets the
 * class when it runs. */
export function withThemeClass(html: string, theme?: "light" | "dark"): string {
  if (!theme) return html;
  const name = `corelata-theme-${theme}`;
  const tag = /<html\b[^>]*>/i.exec(html);
  if (!tag) return html;
  const quoted = /(\sclass\s*=\s*)(["'])/i.exec(tag[0]);
  const themed = quoted
    ? tag[0].slice(0, quoted.index + quoted[0].length) +
      `${name} ` +
      tag[0].slice(quoted.index + quoted[0].length)
    : tag[0].replace(/\s*\/?>$/, (end) => ` class="${name}"${end}`);
  return html.slice(0, tag.index) + themed + html.slice(tag.index + tag[0].length);
}

/** The report with its policy at the top of `<head>`, whatever the tag's attributes (R-M10-8);
 * right after the doctype when there is no head (so the document stays in standards mode); else
 * at the very start. The built theme's class goes on `<html>` (`withThemeClass`). The bridge is
 * appended inside `<body>` (or at the end). */
export function withBridge(
  source: string,
  nonce: string = frameNonce(),
  theme?: "light" | "dark",
): string {
  const html = withThemeClass(source, theme);
  const meta = cspMeta(nonce);
  const anchor = /<head\b[^>]*>/i.exec(html) ?? /^\s*<!doctype\b[^>]*>/i.exec(html);
  const cut = anchor ? anchor.index + anchor[0].length : 0;
  const withMeta = html.slice(0, cut) + meta + html.slice(cut);
  const script = bridgeScript(nonce, theme);
  const at = [...withMeta.matchAll(/<\/body\s*>/gi)].at(-1)?.index; // length-preserving search
  return at === undefined ? withMeta + script : withMeta.slice(0, at) + script + withMeta.slice(at);
}
