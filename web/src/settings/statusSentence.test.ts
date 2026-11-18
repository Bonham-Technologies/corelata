import type { DoctorCheck } from "../api/types";
import { reportFailed, statusSentence } from "./statusSentence";

const check = (name: string, status: DoctorCheck["status"], message = "m"): DoctorCheck => ({
  name,
  status,
  message,
  fix: "",
});
const say = (...checks: DoctorCheck[]) => statusSentence({ checks, ok: true });

it("says everything is working, and how many notes wait under Technical details", () => {
  expect(say(check("config", "pass"))).toBe("Everything is working.");
  expect(say(check("config", "warn"))).toBe(
    "Everything is working. 1 note is under Technical details.",
  );
  expect(say(check("config", "warn"), check("pack", "warn"))).toBe(
    "Everything is working. 2 notes are under Technical details.",
  );
});

it.each([
  [
    "database",
    "Corelata can't reach its database. Reports can't start until an administrator fixes it.",
  ],
  [
    "backends",
    "The model server isn't answering. Reports can't be written until an administrator fixes it.",
  ],
  [
    "backend local",
    "The model server isn't answering. Reports can't be written until an administrator fixes it.",
  ],
  [
    "model m1 auditor schema",
    "The model server isn't answering. Reports can't be written until an administrator fixes it.",
  ],
  [
    "storage",
    "Corelata can't store files. Uploads and reports fail until an administrator fixes it.",
  ],
  [
    "pack",
    "Something needs an administrator's attention. The details are under Technical details.",
  ],
])("words a failing %s check", (name, sentence) => {
  expect(say(check("prompts", "pass"), check(name, "fail"))).toBe(sentence);
});

it("quotes the configuration's problem, and lets the first failing check decide", () => {
  expect(say(check("config", "fail", "backends.local.base_url: must not contain a query."))).toBe(
    "The configuration has a problem. An administrator needs to fix it; the details are under Technical details.",
  );
  expect(say(check("storage", "fail"), check("database", "fail"))).toMatch(/^Corelata can't store/);
  expect(reportFailed({ checks: [check("x", "warn")], ok: true })).toBe(false);
  expect(reportFailed({ checks: [check("x", "fail")], ok: false })).toBe(true);
});
