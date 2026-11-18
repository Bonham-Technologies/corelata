import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { startRun } from "./support";

// Runs in the `csp-proxy` project: every response comes through api/csp_proxy.py, which adds the
// operator guide's sample Content-Security-Policy (docs/operator-guide.md, section 6; CRL-23).
const GUIDE = readFileSync(new URL("../../docs/operator-guide.md", import.meta.url), "utf-8");
const SAMPLE = /add_header Content-Security-Policy "([^"]+)" always;/.exec(GUIDE)?.[1];

// In both themes (M18 spec §8.3): the theme script is a file, and the frame's theme classes
// are in the bridge's nonce-bound style, so the sample policy allows both.
for (const theme of ["light", "dark"] as const) {
  test(`a run, its progress and the claim highlight work under the guide's sample policy (${theme})`, async ({
    page,
    request,
  }) => {
    expect(SAMPLE, "the guide's sample policy").toBeTruthy();
    await page.addInitScript((choice) => localStorage.setItem("corelata.theme", choice), theme);
    const violations: string[] = [];
    page.on("console", (message) => {
      if (/Content Security Policy|Refused to|CSP violation/i.test(message.text()))
        violations.push(message.text());
    });
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (event) =>
        console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`),
      );
    });

    const home = await page.goto("/new");
    expect(home?.headers()["content-security-policy"]).toBe(SAMPLE);

    const { runId } = await startRun(request, { label: "CSP", maxIterations: 1 });

    // Progress arrives over the event stream, through the proxy.
    await page.goto(`/runs/${runId}`);
    const review = page.getByRole("link", { name: "Review the report" });
    await expect(review).toBeVisible({ timeout: 90_000 });
    await review.click();

    const frame = page.frameLocator('iframe[title="Report"]');
    await expect(frame.locator("h1")).toBeVisible();
    // The report's own stylesheet applied (allowed by its hash): 46rem at 16px.
    await expect(frame.locator("body")).toHaveCSS("max-width", "736px");
    await page.getByRole("list", { name: "Claims" }).getByRole("button").first().click();
    // The bridge's highlight style applied (allowed by the nonce), on the claim the page chose.
    await expect(frame.locator(".corelata-highlight").first()).toHaveCSS(
      "background-color",
      "rgb(255, 243, 176)",
    );
    await expect(frame.locator("html")).toHaveClass(new RegExp(`\\bcorelata-theme-${theme}\\b`));
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expect(violations, "no Content-Security-Policy violation").toEqual([]);

    // The same policy still blocks what the frame has no hash or nonce for: an inline script and
    // an inline style added to the report are refused, whatever the theme.
    const blocked = await frame.locator("body").evaluate(async (body) => {
      const doc = body.ownerDocument;
      // Resolves once both refusals have been reported; the listener is attached first.
      const refused = new Promise<string[]>((resolve) => {
        const seen: string[] = [];
        doc.addEventListener("securitypolicyviolation", (event) => {
          seen.push(event.violatedDirective);
          if (
            seen.some((d) => d.startsWith("script-src")) &&
            seen.some((d) => d.startsWith("style-src"))
          )
            resolve(seen);
        });
      });
      const script = doc.createElement("script");
      script.textContent = "document.documentElement.dataset.inlineScript = 'ran'";
      doc.head.append(script);
      const style = doc.createElement("style");
      style.textContent = "body { outline: 7px solid rgb(1, 2, 3) !important; }";
      doc.head.append(style);
      const directives = await refused;
      return {
        directives,
        scriptRan: doc.documentElement.dataset.inlineScript === "ran",
        outline: doc.defaultView!.getComputedStyle(body).outlineStyle,
      };
    });
    expect(blocked.scriptRan, "the inline script did not run").toBe(false);
    expect(blocked.outline, "the inline style did not apply").toBe("none");
    expect(blocked.directives.some((d) => d.startsWith("script-src"))).toBe(true);
    expect(blocked.directives.some((d) => d.startsWith("style-src"))).toBe(true);
  });
}
