/** Routing for the front door (copied from Coglossa, spec §12.2). Pure: middleware.ts turns a Decision into a
 * response. */
import {
  type Account,
  ITERATIONS,
  parseUsers,
  readCookie,
  readSession,
  signSession,
  verifyPassword,
} from "./auth.js";

export const SESSION_COOKIE = "crl_session";
const WEEK_S = 7 * 24 * 3600;
const COOKIE_ATTRS = "Path=/; HttpOnly; Secure; SameSite=Lax";
const OPEN_PATHS = new Set(["/login", "/login.html", "/robots.txt"]); // robots.txt turns crawlers away
// Identity and Modal proxy-auth headers are replaced; the session cookie must not reach the
// API; Host must stay the API origin's (Modal routes by Host).
const STRIPPED_HEADERS = [
  "x-remote-user",
  "x-remote-groups",
  "x-corelata-proxy-secret",
  "modal-key",
  "modal-secret",
  "cookie",
  "host",
];
const SAFE_METHODS = new Set(["GET", "HEAD"]);
// Verified for names that do not exist, so known and unknown names take the same time.
// Made with hashPassword at the production iteration count; it matches no real password.
const DUMMY_HASH = "pbkdf2_sha256$600000$ISUExc42f4gJFEKFX+3rlA==$3KfiTf3JiTZWRBa6KSkcWL2Ylojqoo6tkRYDZzbtINo=";

export interface Env {
  users: Map<string, Account>;
  sessionSecret: string;
  apiOrigin: string;
  proxySecret: string;
  modalKey: string; // Modal proxy auth: the API endpoint refuses requests without them
  modalSecret: string;
  failDelayMs: number;
}

export type Decision =
  | { kind: "next" }
  | { kind: "redirect"; location: string; setCookie: string | null }
  | { kind: "unauthorized" }
  | { kind: "misconfigured" }
  | { kind: "forbidden" }
  | { kind: "forward"; url: string; headers: Headers };

export function readEnv(env: Record<string, string | undefined> = process.env): Env {
  return {
    users: parseUsers(env.CORELATA_USERS),
    sessionSecret: env.CORELATA_SESSION_SECRET ?? "",
    apiOrigin: (env.CORELATA_API_ORIGIN ?? "").replace(/\/+$/, ""),
    proxySecret: env.CORELATA_PROXY_SECRET ?? "",
    modalKey: env.CORELATA_MODAL_KEY ?? "",
    modalSecret: env.CORELATA_MODAL_SECRET ?? "",
    failDelayMs: 1000,
  };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function signIn(request: Request, env: Env, now: number): Promise<Decision> {
  const form = await request.formData().catch(() => new FormData());
  const name = String(form.get("name") ?? "").trim();
  const encoded = env.users.get(name)?.hash;
  const ok = await verifyPassword(String(form.get("password") ?? ""), encoded ?? DUMMY_HASH);
  if (!encoded || !ok) {
    await sleep(env.failDelayMs); // slows password guessing; no lockout at demo scale
    return { kind: "redirect", location: "/login?failed=1", setCookie: null };
  }
  const value = await signSession(name, now + WEEK_S * 1000, env.sessionSecret);
  return {
    kind: "redirect",
    location: "/",
    setCookie: `${SESSION_COOKIE}=${value}; ${COOKIE_ATTRS}; Max-Age=${WEEK_S}`,
  };
}

export async function decide(request: Request, env: Env, now: number): Promise<Decision> {
  const url = new URL(request.url);
  if (OPEN_PATHS.has(url.pathname) && request.method !== "POST") return { kind: "next" };
  if (
    env.sessionSecret.length < 32 ||
    !env.apiOrigin.startsWith("https://") || // the proxy secret must never travel in cleartext
    !env.proxySecret ||
    !env.modalKey ||
    !env.modalSecret ||
    env.users.size === 0
  ) {
    return { kind: "misconfigured" };
  }
  const origin = request.headers.get("origin");
  const isApi = url.pathname === "/api" || url.pathname.startsWith("/api/");
  const isPost = request.method === "POST";
  const changes =
    (isPost && (url.pathname === "/login" || url.pathname === "/logout")) ||
    (isApi && !SAFE_METHODS.has(request.method));
  if (changes && origin !== null && origin !== url.origin) return { kind: "forbidden" }; // CSRF
  if (url.pathname === "/login") return signIn(request, env, now);
  if (url.pathname === "/logout" && request.method === "POST") {
    return {
      kind: "redirect",
      location: "/login",
      setCookie: `${SESSION_COOKIE}=; ${COOKIE_ATTRS}; Max-Age=0`,
    };
  }
  const cookie = readCookie(request.headers.get("cookie"), SESSION_COOKIE);
  const name = cookie ? await readSession(cookie, env.sessionSecret, now) : null;
  const user = name !== null && env.users.has(name) ? name : null; // removed users are out
  if (user === null) {
    return isApi
      ? { kind: "unauthorized" }
      : { kind: "redirect", location: "/login", setCookie: null };
  }
  if (!isApi) return { kind: "next" };
  return forward(request, url, { name: user, groups: env.users.get(user)!.groups }, env);
}

/** The /api rewrite: the client's identity and proxy headers replaced by the front door's. */
export function forward(
  request: Request,
  url: URL,
  user: { name: string; groups: string[] },
  env: Env,
): Decision {
  const headers = new Headers(request.headers);
  for (const h of STRIPPED_HEADERS) headers.delete(h);
  const names: string[] = [];
  headers.forEach((_, name) => names.push(name));
  for (const name of names) if (name.startsWith("x-middleware-")) headers.delete(name);
  headers.set("x-remote-user", user.name);
  headers.set("x-remote-groups", user.groups.join(",")); // always set: never the client's
  headers.set("x-corelata-proxy-secret", env.proxySecret);
  headers.set("modal-key", env.modalKey);
  headers.set("modal-secret", env.modalSecret);
  return { kind: "forward", url: `${env.apiOrigin}${url.pathname}${url.search}`, headers };
}
