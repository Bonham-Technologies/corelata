import { describe, expect, it } from "vitest";
import { ROBOTS_TAG, respond } from "./respond";
import type { Decision } from "./route";

// The demo is a private sign-in page: no response it sends may be indexed (CRL-98).
describe("respond", () => {
  const decisions: Decision[] = [
    { kind: "next" },
    { kind: "redirect", location: "/login", setCookie: null },
    { kind: "redirect", location: "/", setCookie: "crl_session=v; Path=/" },
    { kind: "unauthorized" },
    { kind: "misconfigured" },
    { kind: "forbidden" },
    { kind: "forward", url: "https://api.example/api/me", headers: new Headers({ "x-remote-user": "ana" }) },
  ];

  it("asks search engines not to index or follow", () => {
    expect(ROBOTS_TAG).toBe("noindex, nofollow");
  });

  it.each(decisions.map((d) => [d.kind, d] as const))("sends X-Robots-Tag on a %s response", (_, d) => {
    expect(respond(d).headers.get("x-robots-tag")).toBe("noindex, nofollow");
  });

  it("lets a page through", () => {
    expect(respond({ kind: "next" }).headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects with 303, setting the cookie only when there is one", () => {
    const plain = respond({ kind: "redirect", location: "/login", setCookie: null });
    expect([plain.status, plain.headers.get("location"), plain.headers.get("set-cookie")]).toEqual([
      303,
      "/login",
      null,
    ]);
    const signedIn = respond({ kind: "redirect", location: "/", setCookie: "crl_session=v; Path=/" });
    expect(signedIn.headers.get("set-cookie")).toBe("crl_session=v; Path=/");
  });

  it("answers 401, 503 and 403 with their messages", async () => {
    const unauthorized = respond({ kind: "unauthorized" });
    expect([unauthorized.status, await unauthorized.json()]).toEqual([401, { detail: "signed out: sign in again" }]);
    const misconfigured = respond({ kind: "misconfigured" });
    expect([misconfigured.status, await misconfigured.text()]).toEqual([503, "The Corelata demo is not configured."]);
    const forbidden = respond({ kind: "forbidden" });
    expect([forbidden.status, await forbidden.text()]).toEqual([403, "Cross-site request refused."]);
  });

  it("rewrites an API call to the origin with the front door's request headers", () => {
    const r = respond({
      kind: "forward",
      url: "https://api.example/api/me",
      headers: new Headers({ "x-remote-user": "ana" }),
    });
    expect(r.headers.get("x-middleware-rewrite")).toBe("https://api.example/api/me");
    expect(r.headers.get("x-middleware-request-x-remote-user")).toBe("ana");
  });
});
