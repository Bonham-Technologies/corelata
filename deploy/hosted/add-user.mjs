#!/usr/bin/env node
// Usage: node --experimental-strip-types deploy/hosted/add-user.mjs <name> [--groups a,b]
// Reads the password from stdin (twice, hidden on a TTY) and prints the line to add to
// CORELATA_USERS. Import goes through Node's type stripping (Node >= 22.6).
import { createInterface } from "node:readline";
import { Writable } from "node:stream";
import { GROUP_NAME, hashPassword, isValidName } from "./vercel/lib/auth.ts";

const [name, flag, list] = process.argv.slice(2);
if (!name || (flag !== undefined && (flag !== "--groups" || list === undefined))) {
  console.error("usage: node --experimental-strip-types deploy/hosted/add-user.mjs <name> [--groups a,b]");
  process.exit(2);
}
// Groups are kept for Coglossa's account shape (Corelata ignores them, spec §12.2)
const groups = (list ?? "").split(",").map((g) => g.trim()).filter((g) => g !== "");
if (!groups.every((g) => GROUP_NAME.test(g))) {
  console.error("group names: letters, digits, spaces, '.', '_' or '-' (1-64 characters)");
  process.exit(2);
}

if (!isValidName(name)) {
  console.error(
    "name must be printable ASCII (letters, digits, punctuation, inner spaces) with no leading or trailing space",
  );
  process.exit(2);
}

let muted = false;
const out = new Writable({
  write(chunk, _enc, done) {
    if (!muted) process.stderr.write(chunk);
    done();
  },
});
const rl = createInterface({ input: process.stdin, output: out, terminal: Boolean(process.stdin.isTTY) });
const lines = [];
rl.on("line", (l) => lines.push(l));
let closed = false;
rl.on("close", () => {
  closed = true;
});

// Waits for line `index`; gives up (undefined) if the input closes first (Ctrl-D, Ctrl-C, EOF).
async function ask(prompt, index) {
  const tty = Boolean(process.stdin.isTTY);
  if (tty) {
    process.stderr.write(prompt);
    muted = true;
  }
  while (lines.length <= index && !closed) await new Promise((r) => setTimeout(r, 20));
  if (tty) {
    muted = false;
    process.stderr.write("\n");
  }
  return lines[index];
}

const first = await ask("Password: ", 0);
const second = await ask("Again: ", 1);
rl.close();
if (!first || first !== second) {
  console.error(first === undefined || second === undefined ? "input closed; no user added" : "passwords empty or did not match");
  process.exit(1);
}
const hash = await hashPassword(first);
const value = groups.length > 0 ? { hash, groups } : hash;
console.log(`${JSON.stringify(name)}: ${JSON.stringify(value)}`);
