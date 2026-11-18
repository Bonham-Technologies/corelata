import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { REPORT_STYLE_HASH } from "virtual:report-style";
import { reportHtml } from "../../test/fixtures";
import {
  FRAME_CSP,
  HIGHLIGHT_CSS,
  bridgeScript,
  cspMeta,
  frameNonce,
  installFrameBridge,
  withBridge,
  type FrameToHost,
  type HostToFrame,
} from "./frameBridge";

function install(html = reportHtml, nonce = "n0nce+/=") {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const posted: FrameToHost[] = [];
  let handler: ((message: HostToFrame) => void) | undefined;
  installFrameBridge(
    doc,
    (m) => posted.push(m),
    (h) => (handler = h),
    HIGHLIGHT_CSS,
    nonce,
  );
  const click = (el: Element) =>
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  return { doc, posted, send: (m: unknown) => handler!(m as HostToFrame), click };
}

it("adds the highlight stylesheet to the frame, bound to the nonce, and reports ready", () => {
  const { doc, posted } = install();
  const style = doc.head.querySelector("style:last-of-type");
  expect(style?.textContent).toBe(HIGHLIGHT_CSS);
  expect(style?.getAttribute("nonce")).toBe("n0nce+/=");
  expect(posted).toEqual([{ type: "corelata:ready" }]);
  const unbound = install(reportHtml, "").doc.head.querySelector("style:last-of-type");
  expect(unbound?.hasAttribute("nonce")).toBe(false); // no nonce, no attribute
});

it("posts the first claim of a clicked cited element and nothing for an unclaimed one", () => {
  const { doc, posted, click } = install();
  click(doc.querySelector('li[data-claim-ids="c1 c3"]')!);
  click(doc.querySelector('p[data-claim-ids=""]')!);
  click(doc.querySelector("h1")!);
  expect(posted.slice(1)).toEqual([{ type: "corelata:select", claim: "c1" }]);
});

it("highlights the claim it is told to, scrolls only on request, and clears", () => {
  const { doc, send } = install();
  const scroll = vi.fn();
  const original = Element.prototype.scrollIntoView;
  onTestFinished(() => {
    Element.prototype.scrollIntoView = original;
  });
  Element.prototype.scrollIntoView = scroll;
  send({ type: "corelata:highlight", claim: "c3", scroll: true });
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(1);
  expect(scroll).toHaveBeenCalledWith({ block: "center" });
  send({ type: "corelata:highlight", claim: "c1", scroll: false });
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(2);
  expect(scroll).toHaveBeenCalledTimes(1);
  send({ type: "corelata:highlight", claim: "c99", scroll: true });
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(0);
  expect(scroll).toHaveBeenCalledTimes(1);
  send({ type: "corelata:highlight", claim: null, scroll: true });
  send({ type: "something-else" });
  send(null);
  expect(doc.querySelectorAll(".corelata-highlight")).toHaveLength(0);
});

it("makes links inert", () => {
  const { doc, click } = install(
    reportHtml.replace("<article>", '<article><a href="https://example.test/x">out</a>'),
  );
  expect(click(doc.querySelector("a")!)).toBe(false); // preventDefault() was called
  expect(click(doc.querySelector("h1")!)).toBe(true);
});

it("serialises the installer into the document before </body>, bound to the nonce", () => {
  const script = bridgeScript("n0nce+/=");
  expect(script.startsWith('<script nonce="n0nce+/=">')).toBe(true);
  expect(script).toContain("corelata:highlight");
  expect(script).toContain(`${JSON.stringify(HIGHLIGHT_CSS)}, "n0nce+/=");</script>`);
  expect(bridgeScript().startsWith("<script>")).toBe(true); // no nonce, no attribute
  expect(bridgeScript()).toContain(`${JSON.stringify(HIGHLIGHT_CSS)}, "");</script>`);
  const out = withBridge(reportHtml, "n0nce+/=");
  expect(out).toContain(`${script}</body>`);
  expect(out).toContain(`<head>${cspMeta("n0nce+/=")}`);
  expect(out.indexOf("<meta http-equiv")).toBeLessThan(out.indexOf("<style"));
  expect(withBridge("<p>no head or body</p>", "n")).toBe(
    `${cspMeta("n")}<p>no head or body</p>${bridgeScript("n")}`,
  );
});

it("locks the frame down: nothing loads, the bridge runs by nonce, the report style by hash", () => {
  expect(FRAME_CSP("abc")).toBe(
    `default-src 'none'; script-src 'nonce-abc'; style-src '${REPORT_STYLE_HASH}' 'nonce-abc'; img-src data:; connect-src 'none'`,
  );
  expect(FRAME_CSP("abc")).not.toContain("unsafe-inline"); // R-M14-2: no inline-style allowance
  expect(cspMeta("abc")).toBe(
    `<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP("abc")}">`,
  );
  const a = frameNonce();
  const b = frameNonce();
  expect(a).not.toBe(b);
  expect(a).toMatch(/^[A-Za-z0-9+/]+=*$/); // base64: legal in a CSP nonce and an attribute
  expect(a.length).toBeGreaterThanOrEqual(22); // 128 bits
});

it("hashes the engine's report stylesheet, the text of the report's one style element", () => {
  // engine/tests/render/test_html.py pins that the rendered <style> holds exactly this file.
  // From this file, as vite.config.ts does, not from the directory the tests run in. Not
  // `new URL(path, import.meta.url)`: Vite rewrites that pattern into an asset URL.
  const here = dirname(fileURLToPath(import.meta.url));
  const css = readFileSync(
    resolve(here, "../../../../engine/corelata/render/templates/report.css"),
  );
  expect(REPORT_STYLE_HASH).toBe(`sha256-${createHash("sha256").update(css).digest("base64")}`);
  expect(REPORT_STYLE_HASH).toMatch(/^sha256-[A-Za-z0-9+/]{43}=$/);
});

it("finds the closing tag by position in the original, whatever the case or characters", () => {
  const doc = "<html><body><p>İstanbul</p></BODY></html>"; // "İ" lowercases to two code units
  expect(withBridge(doc, "n")).toBe(
    `${cspMeta("n")}<html><body><p>İstanbul</p>${bridgeScript("n")}</BODY></html>`,
  );
});

it("puts the policy inside a head that has attributes, after the doctype", () => {
  const doc =
    '<!DOCTYPE html><html lang="bg"><head lang="bg"><title>t</title></head>' +
    "<body><p>x</p></body></html>";
  const out = withBridge(doc, "n");
  expect(out).toBe(
    `<!DOCTYPE html><html lang="bg"><head lang="bg">${cspMeta("n")}<title>t</title></head>` +
      `<body><p>x</p>${bridgeScript("n")}</body></html>`,
  );
  const parsed = new DOMParser().parseFromString(out, "text/html");
  expect(parsed.head.querySelector('meta[http-equiv="Content-Security-Policy"]')).not.toBeNull();
  expect(parsed.doctype?.name).toBe("html");
});

it("puts the policy right after the doctype when there is no head, and <header> is not one", () => {
  expect(withBridge("<!doctype html><header>h</header><p>x</p>", "n")).toBe(
    `<!doctype html>${cspMeta("n")}<header>h</header><p>x</p>${bridgeScript("n")}`,
  );
});

it("writes the built theme into the <html> start tag, so the first paint is already in it", () => {
  const out = withBridge(reportHtml, "n", "dark");
  expect(out).toMatch(/^<!DOCTYPE html><html lang="en" class="corelata-theme-dark"><head>/);
  const parsed = new DOMParser().parseFromString(out, "text/html");
  expect(parsed.documentElement.classList.contains("corelata-theme-dark")).toBe(true);
  // the bridge still sets it, and the parent's later corelata:theme messages still switch it
  expect(out).toContain(`"n", "dark");</script>`);
  // the policy and the nonce are those of a frame built without a theme
  expect(out).toContain(`<head>${cspMeta("n")}`);
  expect(out.replace(' class="corelata-theme-dark"', "")).toBe(
    withBridge(reportHtml, "n").replace(`"n");</script>`, `"n", "dark");</script>`),
  );
});

it("adds the theme class to a class the <html> tag already has, and to no tag when there is none", () => {
  expect(withBridge('<html class="x" lang="bg"><body></body></html>', "n", "light")).toMatch(
    /<html class="corelata-theme-light x" lang="bg">/,
  );
  expect(withBridge("<HTML data-x='1' class='y'><body></body></HTML>", "n", "light")).toMatch(
    /<HTML data-x='1' class='corelata-theme-light y'>/,
  );
  expect(withBridge("<p>no html tag</p>", "n", "dark")).toBe(
    `${cspMeta("n")}<p>no html tag</p>${bridgeScript("n", "dark")}`,
  );
  // no theme: the start tag is left as it is
  expect(withBridge(reportHtml, "n")).toContain('<html lang="en"><head>');
});
