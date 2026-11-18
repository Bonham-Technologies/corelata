/** Sign-in for the hosted demo (copied from Coglossa's front door, spec §12.2): PBKDF2 password hashes and HMAC-signed session
 * cookies, using WebCrypto only, so it runs in Vercel Routing Middleware. */

const enc = new TextEncoder();
export const ITERATIONS = 600_000;

const b64 = (bytes: ArrayBuffer | Uint8Array): string =>
  btoa(String.fromCharCode(...new Uint8Array(bytes)));
const unb64 = (text: string): Uint8Array<ArrayBuffer> => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
const b64url = (text: string): string =>
  btoa(String.fromCharCode(...enc.encode(text)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
const unb64url = (text: string): string =>
  new TextDecoder().decode(unb64(text.replace(/-/g, "+").replace(/_/g, "/")));

async function pbkdf2(password: string, salt: Uint8Array<ArrayBuffer>, iterations: number): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, [
    "deriveBits",
  ]);
  return crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, 256);
}

function equal(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export async function hashPassword(
  password: string,
  { iterations = ITERATIONS }: { iterations?: number } = {},
): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  return `pbkdf2_sha256$${iterations}$${b64(salt)}$${b64(await pbkdf2(password, salt, iterations))}`;
}

export async function verifyPassword(password: string, encoded: string): Promise<boolean> {
  const parts = encoded.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2_sha256") return false;
  const iterations = Number(parts[1]);
  if (!Number.isInteger(iterations) || iterations < 1) return false;
  try {
    const got = new Uint8Array(await pbkdf2(password, unb64(parts[2]), iterations));
    return equal(got, unb64(parts[3]));
  } catch {
    return false; // a salt or hash that is not base64
  }
}

/** Names go into an HTTP header, so they must be printable ASCII (0x20-0x7E) with no leading or
 * trailing space. */
export const isValidName = (name: string): boolean =>
  /^[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?$/.test(name);

/** A user of the front door: a password hash and groups. Accounts keep Coglossa's shape, so
 * one CORELATA_USERS line can be copied from Coglossa's; Corelata has no roles and ignores the
 * groups, but the front door still strips and sets x-remote-groups (spec §12.2). */
export type Account = { hash: string; groups: string[] };

// Coglossa's team name pattern (coglossa.people.TEAM_NAME_PATTERN): no commas, so the header
// splits.
export const GROUP_NAME = /^[A-Za-z0-9._-](?:[A-Za-z0-9._ -]{0,62}[A-Za-z0-9._-])?$/;

function account(value: unknown): Account | null {
  if (typeof value === "string") return { hash: value, groups: [] };
  if (typeof value !== "object" || value === null) return null;
  const { hash, groups = [] } = value as { hash?: unknown; groups?: unknown };
  if (typeof hash !== "string" || !Array.isArray(groups)) return null;
  if (!groups.every((g) => typeof g === "string" && GROUP_NAME.test(g))) return null;
  return { hash, groups: groups as string[] };
}

/** Parses CORELATA_USERS: name → password hash, or name → {hash, groups}. Anything malformed
 * yields an empty map (which the front door treats as misconfigured); a bad name or account
 * rejects the whole map rather than being silently skipped, so a typo cannot go unnoticed. */
export function parseUsers(json: string | undefined): Map<string, Account> {
  try {
    const data: unknown = JSON.parse(json ?? "");
    if (typeof data !== "object" || data === null || Array.isArray(data)) return new Map();
    const users = new Map<string, Account>();
    for (const [name, value] of Object.entries(data as Record<string, unknown>)) {
      const parsed = account(value);
      if (parsed === null || !isValidName(name)) return new Map();
      users.set(name, parsed);
    }
    return users;
  } catch {
    return new Map();
  }
}

async function mac(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return b64(await crypto.subtle.sign("HMAC", key, enc.encode(body)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** `<base64url(name|expiresAtMs)>.<HMAC>`; the name is everything before the last "|". */
export async function signSession(name: string, expiresAt: number, secret: string): Promise<string> {
  const body = b64url(`${name}|${expiresAt}`);
  return `${body}.${await mac(body, secret)}`;
}

export async function readSession(
  value: string,
  secret: string,
  now: number,
): Promise<string | null> {
  const parts = value.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  const expected = await mac(parts[0], secret);
  if (!equal(enc.encode(expected), enc.encode(parts[1]))) return null;
  let decoded: string;
  try {
    decoded = unb64url(parts[0]);
  } catch {
    return null;
  }
  const cut = decoded.lastIndexOf("|");
  const expiresAt = Number(decoded.slice(cut + 1));
  if (cut < 1 || !Number.isFinite(expiresAt) || now > expiresAt) return null;
  return decoded.slice(0, cut);
}

export function readCookie(header: string | null, name: string): string | null {
  for (const part of (header ?? "").split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}
