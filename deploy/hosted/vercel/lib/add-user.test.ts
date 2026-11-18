import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const script = new URL("../../add-user.mjs", import.meta.url).pathname;
const run = (name: string, input: string) =>
  spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", script, name], {
    input,
    encoding: "utf8",
  });

describe("add-user.mjs", () => {
  const withGroups = (name: string, groups: string) =>
    spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", script, name, "--groups", groups], {
      input: "pw\npw\n",
      encoding: "utf8",
    });
  it("adds groups with --groups", () => {
    const r = withGroups("ci", "reviewers, demo,");
    expect(r.status).toBe(0);
    const users = JSON.parse(`{${r.stdout}}`);
    expect(users.ci.groups).toEqual(["reviewers", "demo"]);
    expect(users.ci.hash).toMatch(/^pbkdf2_sha256\$600000\$/);
  });
  it("refuses a bad group name", () => {
    const r = withGroups("ci", "ok,a/b");
    expect(r.status).not.toBe(0);
    expect(r.stdout).toBe("");
    expect(r.stderr).toMatch(/group names/);
  });
  it("prints a CORELATA_USERS line for a valid name", () => {
    const r = run("ana", "pw\npw\n");
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/^"ana": "pbkdf2_sha256\$600000\$[^"]+"\n$/);
  });
  it("quotes a name with JSON escapes, so the line is valid inside the JSON object", () => {
    const r = run('a"b\\c', "pw\npw\n");
    expect(r.status).toBe(0);
    const users = JSON.parse(`{${r.stdout}}`);
    expect(Object.keys(users)).toEqual(['a"b\\c']);
    expect(users['a"b\\c']).toMatch(/^pbkdf2_sha256\$600000\$/);
  });
  it("refuses a name that is not printable ASCII", () => {
    for (const bad of ["Анна", " ana"]) {
      const r = run(bad, "pw\npw\n");
      expect(r.status).not.toBe(0);
      expect(r.stdout).toBe("");
      expect(r.stderr).toMatch(/printable ASCII/);
    }
  });
  it("exits non-zero without a hash when input closes early or does not match", () => {
    for (const input of ["", "pw\n", "pw\nother\n"]) {
      const r = run("ana", input);
      expect(r.status).not.toBe(0);
      expect(r.stdout).toBe("");
    }
  });
});
