import { beforeEach, describe, expect, it, vi } from "vitest";
import * as auth from "./auth";
import { type Account, hashPassword, signSession } from "./auth";

vi.mock("./auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./auth")>();
  return { ...actual, verifyPassword: vi.fn(actual.verifyPassword) };
});
import { decide, type Env, readEnv, SESSION_COOKIE } from "./route";

const SECRET = "s".repeat(32);
const NOW = 1_000_000;

async function env(): Promise<Env> {
  return {
    users: new Map([
      ["ana", { hash: await hashPassword("pw", { iterations: 1000 }), groups: [] }],
      ["ci", { hash: "unused", groups: ["reviewers", "demo"] }],
    ]),
    sessionSecret: SECRET,
    apiOrigin: "https://ws--corelata-api.modal.run",
    proxySecret: "p".repeat(32),
    modalKey: "wk-test",
    modalSecret: "ws-test",
    failDelayMs: 0,
  };
}

async function signedIn(path: string, init: RequestInit = {}, name = "ana"): Promise<Request> {
  const cookie = `${SESSION_COOKIE}=${await signSession(name, NOW + 60_000, SECRET)}`;
  const headers = new Headers(init.headers);
  headers.set("cookie", cookie);
  return new Request(`https://preview.example${path}`, { ...init, headers });
}

describe("decide", () => {
  it("lets the login page and its stylesheet through", async () => {
    for (const path of ["/login", "/login.html"]) {
      expect((await decide(new Request(`https://p.example${path}`), await env(), NOW)).kind).toBe(
        "next",
      );
    }
  });

  it("serves robots.txt signed out, even when misconfigured", async () => {
    const req = () => new Request("https://p.example/robots.txt");
    expect((await decide(req(), await env(), NOW)).kind).toBe("next");
    expect((await decide(req(), { ...(await env()), users: new Map() }, NOW)).kind).toBe("next");
  });

  it("sends a signed-out page view to /login", async () => {
    const d = await decide(new Request("https://p.example/projects"), await env(), NOW);
    expect(d).toEqual({ kind: "redirect", location: "/login", setCookie: null });
  });

  it("answers a signed-out API call with 401", async () => {
    const d = await decide(new Request("https://p.example/api/me"), await env(), NOW);
    expect(d.kind).toBe("unauthorized");
  });

  it("signs in with the right password and sets a 7-day cookie", async () => {
    const body = new URLSearchParams({ name: "ana", password: "pw" });
    const d = await decide(
      new Request("https://p.example/login", { method: "POST", body }),
      await env(),
      NOW,
    );
    expect(d.kind).toBe("redirect");
    if (d.kind !== "redirect") throw new Error();
    expect(d.location).toBe("/");
    expect(d.setCookie).toMatch(
      /^crl_session=[^;]+; Path=\/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800$/,
    );
  });

  it("refuses a wrong password or unknown user", async () => {
    for (const [name, password] of [
      ["ana", "nope"],
      ["bob", "pw"],
      ["", ""],
    ]) {
      const body = new URLSearchParams({ name, password });
      const d = await decide(
        new Request("https://p.example/login", { method: "POST", body }),
        await env(),
        NOW,
      );
      expect(d).toEqual({ kind: "redirect", location: "/login?failed=1", setCookie: null });
    }
  });

  it("refuses a login post with no parseable form", async () => {
    const d = await decide(
      new Request("https://p.example/login", { method: "POST", body: "{}" }),
      await env(),
      NOW,
    );
    expect(d).toEqual({ kind: "redirect", location: "/login?failed=1", setCookie: null });
  });

  it("signs out", async () => {
    const d = await decide(await signedIn("/logout", { method: "POST" }), await env(), NOW);
    expect(d).toEqual({
      kind: "redirect",
      location: "/login",
      setCookie: "crl_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
    });
  });

  it("forwards API calls with its own identity headers, stripping the client's", async () => {
    const d = await decide(
      await signedIn("/api/projects?limit=5", {
        headers: {
          "x-remote-user": "mallory",
          "x-remote-groups": "reviewers",
          "x-corelata-proxy-secret": "guess",
          "modal-key": "wk-guess",
          "modal-secret": "ws-guess",
          host: "preview.example",
          "x-middleware-request-x-remote-user": "evil",
          "x-middleware-next": "1",
          "x-keep": "yes",
        },
      }),
      await env(),
      NOW,
    );
    expect(d.kind).toBe("forward");
    if (d.kind !== "forward") throw new Error();
    expect(d.url).toBe("https://ws--corelata-api.modal.run/api/projects?limit=5");
    expect(d.headers.get("x-remote-user")).toBe("ana");
    expect(d.headers.get("x-remote-groups")).toBe(""); // ana has none; the client's is dropped
    expect(d.headers.get("x-corelata-proxy-secret")).toBe("p".repeat(32));
    expect(d.headers.get("modal-key")).toBe("wk-test");
    expect(d.headers.get("modal-secret")).toBe("ws-test");
    expect(d.headers.has("cookie")).toBe(false);
    expect(d.headers.has("host")).toBe(false);
    const names: string[] = [];
    d.headers.forEach((_, name) => names.push(name));
    expect(names.filter((n) => n.startsWith("x-middleware-"))).toEqual([]);
    expect(d.headers.get("x-keep")).toBe("yes");
  });

  it("forwards the signed-in user's groups", async () => {
    const d = await decide(await signedIn("/api/me", {}, "ci"), await env(), NOW);
    if (d.kind !== "forward") throw new Error(d.kind);
    expect(d.headers.get("x-remote-user")).toBe("ci");
    expect(d.headers.get("x-remote-groups")).toBe("reviewers,demo");
  });

  it("serves the web app to a signed-in user", async () => {
    expect((await decide(await signedIn("/projects/1"), await env(), NOW)).kind).toBe("next");
  });

  it("refuses a cookie whose user has been removed", async () => {
    const d = await decide(await signedIn("/api/me", {}, "carol"), await env(), NOW);
    expect(d.kind).toBe("unauthorized");
  });

  it("refuses everything when the front door is misconfigured", async () => {
    const broken = { ...(await env()), sessionSecret: "" };
    const d = await decide(await signedIn("/projects"), broken, NOW);
    expect(d.kind).toBe("misconfigured");
  });

  it("treats a short session secret, empty origin or empty proxy secret as misconfigured", async () => {
    const base = await env();
    const req = new Request("https://p.example/api/me"); // no cookie: no check happens
    for (const bad of [
      { ...base, sessionSecret: "s".repeat(31) },
      { ...base, apiOrigin: "" },
      { ...base, proxySecret: "" },
      { ...base, modalKey: "" },
      { ...base, modalSecret: "" },
    ]) {
      expect((await decide(req, bad, NOW)).kind).toBe("misconfigured");
    }
  });
});

describe("hardening", () => {
  beforeEach(() => {
    vi.mocked(auth.verifyPassword).mockClear();
  });

  const login = async (name: string, password: string, headers: HeadersInit = {}) =>
    decide(
      new Request("https://p.example/login", {
        method: "POST",
        body: new URLSearchParams({ name, password }),
        headers,
      }),
      await env(),
      NOW,
    );

  it("verifies a password even for an unknown name, against a same-cost dummy hash", async () => {
    await login("nobody", "pw");
    const calls = vi.mocked(auth.verifyPassword).mock.calls;
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toMatch(/^pbkdf2_sha256\$600000\$/);
    expect(calls[0][1]).not.toBe(await (await env()).users.get("ana")?.hash);
    await login("ana", "pw");
    expect(vi.mocked(auth.verifyPassword)).toHaveBeenCalledTimes(2);
  });

  it("refuses cross-origin sign-in and sign-out, allows same-origin and no Origin", async () => {
    expect(await login("ana", "pw", { origin: "https://evil.example" })).toEqual({
      kind: "forbidden",
    });
    expect((await login("ana", "pw", { origin: "https://p.example" })).kind).toBe("redirect");
    expect((await login("ana", "pw")).kind).toBe("redirect");
    const out = await decide(
      await signedIn("/logout", { method: "POST", headers: { origin: "https://evil.example" } }),
      await env(),
      NOW,
    );
    expect(out).toEqual({ kind: "forbidden" });
  });

  it("refuses a cross-origin API call that changes something, before checking the session", async () => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      const d = await decide(
        await signedIn("/api/projects", { method, headers: { origin: "https://evil.example" } }),
        await env(),
        NOW,
      );
      expect(d).toEqual({ kind: "forbidden" });
    }
    const signedOut = new Request("https://p.example/api/projects", {
      method: "POST",
      headers: { origin: "https://evil.example" },
    });
    expect(await decide(signedOut, await env(), NOW)).toEqual({ kind: "forbidden" });
  });

  it("forwards same-origin and Origin-less API changes, and cross-origin reads", async () => {
    const cases: [string, HeadersInit][] = [
      ["POST", { origin: "https://preview.example" }],
      ["DELETE", {}],
      ["GET", { origin: "https://evil.example" }],
      ["HEAD", { origin: "https://evil.example" }],
    ];
    for (const [method, headers] of cases) {
      const request = await signedIn("/api/projects", { method, headers });
      const d = await decide(request, await env(), NOW);
      expect(d.kind).toBe("forward");
    }
  });

  it("is misconfigured with a cleartext origin or no users", async () => {
    const req = await signedIn("/api/me");
    for (const bad of [
      { ...(await env()), apiOrigin: "http://api.example" },
      { ...(await env()), apiOrigin: "api.example" },
      { ...(await env()), users: new Map<string, Account>() },
    ]) {
      expect((await decide(req, bad, NOW)).kind).toBe("misconfigured");
    }
  });
});

describe("readEnv", () => {
  it("reads the variables, trims the origin and defaults the fail delay", () => {
    const e = readEnv({
      CORELATA_USERS: '{"ana":"pbkdf2_sha256$1$a$b"}',
      CORELATA_SESSION_SECRET: "s".repeat(32),
      CORELATA_API_ORIGIN: "https://api.example/",
      CORELATA_PROXY_SECRET: "p",
      CORELATA_MODAL_KEY: "wk",
      CORELATA_MODAL_SECRET: "ws",
    });
    expect(e.users.get("ana")).toEqual({ hash: "pbkdf2_sha256$1$a$b", groups: [] });
    expect(e.sessionSecret).toBe("s".repeat(32));
    expect(e.apiOrigin).toBe("https://api.example");
    expect(e.proxySecret).toBe("p");
    expect(e.modalKey).toBe("wk");
    expect(e.modalSecret).toBe("ws");
    expect(e.failDelayMs).toBe(1000);
  });
  it("defaults to empty values and reads process.env", () => {
    const e = readEnv({});
    expect(e.users.size).toBe(0);
    expect(e.sessionSecret).toBe("");
    expect(e.apiOrigin).toBe("");
    expect(e.proxySecret).toBe("");
    expect(e.modalKey).toBe("");
    expect(e.modalSecret).toBe("");
  });
  it("reads process.env by default", () => {
    vi.stubEnv("CORELATA_USERS", '{"ana":"pbkdf2_sha256$1$a$b"}');
    vi.stubEnv("CORELATA_SESSION_SECRET", "q".repeat(32));
    vi.stubEnv("CORELATA_API_ORIGIN", "https://api.example//");
    vi.stubEnv("CORELATA_PROXY_SECRET", "ps");
    vi.stubEnv("CORELATA_MODAL_KEY", "wk-env");
    vi.stubEnv("CORELATA_MODAL_SECRET", "ws-env");
    const e = readEnv();
    vi.unstubAllEnvs();
    expect([...e.users.keys()]).toEqual(["ana"]);
    expect(e.sessionSecret).toBe("q".repeat(32));
    expect(e.apiOrigin).toBe("https://api.example");
    expect(e.proxySecret).toBe("ps");
    expect(e.modalKey).toBe("wk-env");
    expect(e.modalSecret).toBe("ws-env");
    expect(e.failDelayMs).toBe(1000);
  });
});

describe("Corelata's logins (spec §23.3)", () => {
  it("signs in people-first with an account line copied from Coglossa's, groups and all", async () => {
    const hash = await hashPassword("shared", { iterations: 1000 });
    const line = JSON.stringify({ "people-first": { hash, groups: ["demo"] } });
    const e = { ...(await env()), users: readEnv({ CORELATA_USERS: line }).users };
    const body = new URLSearchParams({ name: "people-first", password: "shared" });
    const login = await decide(
      new Request("https://p.example/login", { method: "POST", body }),
      e,
      NOW,
    );
    if (login.kind !== "redirect" || !login.setCookie) throw new Error(login.kind);
    const cookie = login.setCookie.split(";")[0];
    expect(cookie.startsWith(`${SESSION_COOKIE}=`)).toBe(true);
    const call = await decide(
      new Request("https://p.example/api/system/info", { headers: { cookie } }),
      e,
      NOW,
    );
    if (call.kind !== "forward") throw new Error(call.kind);
    expect(call.headers.get("x-remote-user")).toBe("people-first");
    expect(call.url).toBe("https://ws--corelata-api.modal.run/api/system/info");
  });

  it("names its cookie crl_session, apart from Coglossa's cg_session", () => {
    expect(SESSION_COOKIE).toBe("crl_session");
  });
});
