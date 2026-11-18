import { describe, expect, it } from "vitest";
import {
  hashPassword,
  isValidName,
  parseUsers,
  readCookie,
  readSession,
  signSession,
  verifyPassword,
} from "./auth";

const SECRET = "x".repeat(32);

describe("passwords", () => {
  it("verifies a hash it made and rejects a wrong password", async () => {
    const encoded = await hashPassword("correct horse", { iterations: 1000 });
    expect(encoded).toMatch(/^pbkdf2_sha256\$1000\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$/);
    expect(await verifyPassword("correct horse", encoded)).toBe(true);
    expect(await verifyPassword("wrong", encoded)).toBe(false);
  });
  it("rejects malformed hashes", async () => {
    for (const bad of ["", "md5$1$a$b", "pbkdf2_sha256$x$a$b", "pbkdf2_sha256$1000$a"]) {
      expect(await verifyPassword("p", bad)).toBe(false);
    }
  });
  it("rejects a salt or hash that is not base64", async () => {
    expect(await verifyPassword("p", "pbkdf2_sha256$1000$!!!$!!!")).toBe(false);
  });
  it("uses the default iteration count", async () => {
    expect(await hashPassword("p")).toMatch(/^pbkdf2_sha256\$600000\$/);
  });
});

describe("users", () => {
  it("parses the JSON map and refuses anything else", () => {
    expect(parseUsers('{"ana": "pbkdf2_sha256$1$a$b"}').get("ana")).toEqual({
      hash: "pbkdf2_sha256$1$a$b",
      groups: [],
    });
    expect(parseUsers(undefined).size).toBe(0);
    expect(parseUsers("not json").size).toBe(0);
    expect(parseUsers('["ana"]').size).toBe(0);
    expect(parseUsers('{"ana": 3}').size).toBe(0);
    expect(parseUsers("null").size).toBe(0);
  });
  it("rejects the whole map if any name is not printable ASCII without edge spaces", () => {
    const h = "pbkdf2_sha256$1$a$b";
    expect(parseUsers(JSON.stringify({ "Ana Maria": h })).size).toBe(1);
    for (const bad of ["Анна", "ana\n", " ana", "ana ", "", "caf\u00e9", "a\u007f"]) {
      expect(parseUsers(JSON.stringify({ ok: h, [bad]: h })).size).toBe(0);
    }
    expect(isValidName("a")).toBe(true);
  });
  it("reads users with groups, and plain hashes as users without", () => {
    const users = parseUsers(
      JSON.stringify({
        ana: "pbkdf2_sha256$1$a$b",
        ci: { hash: "pbkdf2_sha256$1$c$d", groups: ["reviewers", "demo"] },
        bo: { hash: "pbkdf2_sha256$1$e$f" },
      }),
    );
    expect(users.get("ana")).toEqual({ hash: "pbkdf2_sha256$1$a$b", groups: [] });
    expect(users.get("ci")).toEqual({ hash: "pbkdf2_sha256$1$c$d", groups: ["reviewers", "demo"] });
    expect(users.get("bo")).toEqual({ hash: "pbkdf2_sha256$1$e$f", groups: [] });
  });
  it("rejects the whole map for a malformed account", () => {
    const ok = "pbkdf2_sha256$1$a$b";
    const bad = [{ groups: [] }, { hash: 3 }, { hash: "h", groups: "x" }, { hash: "h", groups: ["a,b"] }];
    for (const b of [...bad, { hash: "h", groups: [" lead"] }, { hash: "h", groups: [7] }, null]) {
      expect(parseUsers(JSON.stringify({ ana: ok, ci: b })).size).toBe(0);
    }
  });
});

describe("sessions", () => {
  it("round-trips a name until it expires", async () => {
    const value = await signSession("ana", 2_000, SECRET);
    expect(await readSession(value, SECRET, 1_000)).toBe("ana");
    expect(await readSession(value, SECRET, 2_001)).toBeNull();
  });
  it("rejects tampering, a wrong secret and garbage", async () => {
    const value = await signSession("ana", 2_000, SECRET);
    const [body, mac] = value.split(".");
    const forged = btoa("bob|2000").replace(/=+$/, "") + "." + mac;
    expect(await readSession(forged, SECRET, 1_000)).toBeNull();
    expect(await readSession(value, "y".repeat(32), 1_000)).toBeNull();
    for (const bad of ["", "abc", `${body}.`, ".x", "a.b.c"]) {
      expect(await readSession(bad, SECRET, 1_000)).toBeNull();
    }
  });
  it("keeps a name containing the separator intact", async () => {
    const value = await signSession("a|b", 2_000, SECRET);
    expect(await readSession(value, SECRET, 1_000)).toBe("a|b");
  });
  it("rejects correctly signed bodies that are malformed", async () => {
    // Sign arbitrary bodies via the module's own MAC by crafting through signSession's format.
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(SECRET),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const sign = async (body: string) => {
      const m = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
      const s = btoa(String.fromCharCode(...m)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
      return `${body}.${s}`;
    };
    const b = (t: string) => btoa(t).replace(/=+$/, "");
    expect(await readSession(await sign(b("ana2000")), SECRET, 1)).toBeNull(); // no separator
    expect(await readSession(await sign(b("|2000")), SECRET, 1)).toBeNull(); // empty name
    expect(await readSession(await sign(b("ana|soon")), SECRET, 1)).toBeNull(); // bad expiry
    expect(await readSession(await sign("%%%"), SECRET, 1)).toBeNull(); // not base64
  });
});

describe("cookies", () => {
  it("finds one cookie among several", () => {
    expect(readCookie("a=1; crl_session=xyz; b=2", "crl_session")).toBe("xyz");
    expect(readCookie(null, "crl_session")).toBeNull();
    expect(readCookie("a=1", "crl_session")).toBeNull();
  });
});
