import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { deferred } from "../../test/deferred";
import { expectNoEngineWords } from "../../test/engine-words";
import { AUDIT_INCOMPLETE, findings, resolvedPack, RUN_ID, runTrace } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { AuditTab, auditRows, standardsGroups } from "./AuditTab";

it("builds one row per rule with the latest verdict and the iteration history", () => {
  const rows = auditRows(findings, resolvedPack.rules);
  expect(
    rows.map((r) => [
      r.ruleId,
      r.title,
      r.latest.verdict,
      r.history.map((h) => h.verdict),
      r.advisory,
    ]),
  ).toEqual([
    ["icd203.tc.8", "Sourcing is clear", "pass", ["fail", "pass"], false],
    ["icd203.tc.7", "Consistent with prior analysis", "attested", ["attested"], true],
  ]);
  const noPack = auditRows(findings, undefined);
  expect(noPack.map((r) => [r.title, r.advisory])).toEqual([
    ["icd203.tc.8", false],
    ["icd203.tc.7", false],
  ]);
});

it("groups an advisory rule checked against earlier reports with the checked rules (CRL-97)", () => {
  const checked = findings.map((f) =>
    f.rule_id === "icd203.tc.7" ? { ...f, verdict: "fail" as const, severity: "minor" } : f,
  );
  const rows = auditRows(checked, resolvedPack.rules);
  expect(rows.map((r) => [r.ruleId, r.advisory])).toEqual([
    ["icd203.tc.8", false],
    ["icd203.tc.7", false],
  ]);
  const groups = standardsGroups(rows);
  expect(groups.minor.map((r) => r.ruleId)).toEqual(["icd203.tc.7"]);
  expect(groups.advisory).toEqual([]);
});

it("groups the rules met and advisory, each with its verdict, severity, why and history", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  const met = await screen.findByRole("list", { name: "Met and not applicable" });
  const rule = within(met).getByRole("listitem");
  expect(rule).toHaveTextContent("Sourcing is clear");
  expect(rule).toHaveTextContent("icd203.tc.8");
  expect(rule).toHaveTextContent("✓ met");
  expect(rule).toHaveTextContent("Blocking");
  const why = within(rule).getByText("Why").closest("details")!;
  expect(why).not.toHaveAttribute("open");
  expect(why).toHaveTextContent("Every claim cites a unit.");
  expect(within(rule).getByLabelText("History")).toHaveTextContent("✗ not met → ✓ met");
  expect(screen.queryByRole("list", { name: "Not met" })).toBeNull();
  const advisory = screen.getByRole("list", { name: "Advisory" });
  expect(within(advisory).getByRole("listitem")).toHaveTextContent(
    "Consistent with prior analysis",
  );
  expect(within(advisory).getByRole("listitem")).toHaveTextContent("◇ attested");
  expect(screen.getByText("Every standard that could be checked was met.")).toBeInTheDocument();
});

it("falls back to rule ids when the pack cannot be resolved", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () =>
      HttpResponse.json({ detail: "pack 'icd203-base' not found" }, { status: 404 }),
    ),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  // without the pack nothing says which rules are advisory: they group by verdict alone
  const met = await screen.findByRole("list", { name: "Met and not applicable" });
  expect(within(met).getAllByRole("listitem")).toHaveLength(2);
  expect(within(met).getAllByRole("listitem")[0]).toHaveTextContent("icd203.tc.8");
  const note = await screen.findByText(/^Rule titles are unavailable:/);
  expect(note).toHaveTextContent("Rule titles are unavailable: pack 'icd203-base' not found");
  // the server's text is marked as the engine's own; our lead-in has no engine word
  expect(note.querySelector("[data-raw-error]")).toHaveTextContent("pack 'icd203-base' not found");
  expectNoEngineWords(document.body, { exceptRawErrors: true });
});

it("says a rule not met in an earlier check and not checked again is still not met", async () => {
  const earlier = findings.filter((f) => f.rule_id === "icd203.tc.8" && f.iteration === 0);
  const later = {
    ...findings[2]!,
    rule_id: "icd203.tc.7",
    iteration: 1,
  };
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([...earlier, later])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  const notMet = await screen.findByRole("list", { name: "Not met" });
  expect(notMet).toHaveTextContent("Sourcing is clear");
  // one meaning of "not met": the notice and the group never show together
  expect(screen.queryByText("Every standard that could be checked was met.")).toBeNull();
});

it("shows a findings error", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () =>
      HttpResponse.json({ detail: "run not found" }, { status: 404 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("run not found");
});

it("says so when no findings were recorded", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  expect(await screen.findByText("No standards results were recorded.")).toBeInTheDocument();
});

it("shows the recommendation and no pass notice while a verifiable rule is failing", async () => {
  const failing = findings.map((f) => ({
    ...f,
    verdict: "fail" as const,
    recommendation: "Cite a unit.",
  }));
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(failing)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  expect((await screen.findAllByText("Cite a unit.")).length).toBeGreaterThan(0);
  // not met comes first; a fail on a rule the pack marks advisory means the run checked it
  // (`with_prior_reports`, CRL-97), so it is a minor issue, not an advisory note
  const groups = screen.getAllByRole("list").map((l) => l.getAttribute("aria-label"));
  expect(groups).toEqual(["Not met", "Minor issues"]);
  expect(screen.queryByText("Every standard that could be checked was met.")).toBeNull();
});

it("shows a loading state for the rule titles instead of reflowing the rules", async () => {
  const pack = deferred();
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", async () => {
      await pack.promise;
      return HttpResponse.json(resolvedPack);
    }),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  expect(await screen.findByText(/Loading rule titles/)).toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Met and not applicable" })).not.toBeInTheDocument();
  pack.resolve();
  const met = await screen.findByRole("list", { name: "Met and not applicable" });
  expect(within(met).getByText("Sourcing is clear")).toHaveAttribute("dir", "auto");
});

const REASON = AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2);

/** The notice's whole text: the reason is its own (raw) element inside the paragraph. */
const notice = (text: string) => (_: string, el: Element | null) =>
  el?.tagName === "P" && el.textContent === text;

it("says the standards check did not finish instead of saying nothing was recorded", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(
    <AuditTab
      runId={RUN_ID}
      degradations={["conveyance skipped after 2 attempts: x", AUDIT_INCOMPLETE]}
    />,
  );
  expect(
    await screen.findByText(notice(`The standards check didn't finish: ${REASON}`)),
  ).toBeInTheDocument();
  expect(screen.queryByText("No standards results were recorded.")).toBeNull();
});

it("shows the whole entry when it has no colon", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} degradations={["audit incomplete"]} />);
  const note = await screen.findByText(
    notice("The standards check didn't finish: audit incomplete"),
  );
  expect(note).toHaveAttribute("dir", "auto");
});

it("keeps the previous check's rules without the met notice", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} degradations={[AUDIT_INCOMPLETE]} />);
  expect(await screen.findByRole("list", { name: "Met and not applicable" })).toBeInTheDocument();
  expect(
    screen.getByText(notice(`The standards check didn't finish: ${REASON}`)),
  ).toBeInTheDocument();
  expect(screen.queryByText("Every standard that could be checked was met.")).toBeNull();
});

it("ignores a conveyance degradation", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(
    <AuditTab runId={RUN_ID} degradations={["conveyance skipped after 2 attempts: x"]} />,
  );
  expect(await screen.findByText("No standards results were recorded.")).toBeInTheDocument();
});

// R-M18-27: "not met" means what the engine's open_findings holds, a latest fail at blocking or
// major severity (engine/corelata/stages/audit.py LOOPING); a latest minor fail is a minor issue.
const PLAIN = "icd203.as.4";
function withPlainWords(severity: "major" | "minor") {
  const pack = {
    ...resolvedPack,
    rules: [
      ...resolvedPack.rules,
      { ...resolvedPack.rules[0]!, id: PLAIN, title: "Plain words", severity },
    ],
  };
  const plain = {
    ...findings[1]!,
    rule_id: PLAIN,
    verdict: "fail" as const,
    severity,
    evidence: "Paragraph 2 uses jargon.",
    iteration: 1,
  };
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([...findings, plain])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(pack)),
  );
}

const groupNames = () => screen.getAllByRole("list").map((l) => l.getAttribute("aria-label"));

it("lists a latest minor fail under Minor issues, with its severity, and not under Not met", async () => {
  withPlainWords("minor");
  renderWithClient(<AuditTab runId={RUN_ID} />);
  const minor = await screen.findByRole("list", { name: "Minor issues" });
  const rule = within(minor).getByRole("listitem");
  expect(rule).toHaveTextContent("Plain words");
  expect(rule).toHaveTextContent("✗ not met");
  expect(rule).toHaveTextContent("Minor");
  expect(screen.queryByRole("list", { name: "Not met" })).toBeNull();
  expect(groupNames()).toEqual(["Minor issues", "Met and not applicable", "Advisory"]);
  expect(
    screen.getByText("Every blocking and major standard that could be checked was met."),
  ).toBeInTheDocument();
  expect(screen.queryByText("Every standard that could be checked was met.")).toBeNull();
});

it("lists a latest major fail under Not met", async () => {
  withPlainWords("major");
  renderWithClient(<AuditTab runId={RUN_ID} />);
  const notMet = await screen.findByRole("list", { name: "Not met" });
  expect(within(notMet).getByRole("listitem")).toHaveTextContent("Plain words");
  expect(within(notMet).getByRole("listitem")).toHaveTextContent("Major");
  expect(screen.queryByRole("list", { name: "Minor issues" })).toBeNull();
  expect(groupNames()).toEqual(["Not met", "Met and not applicable", "Advisory"]);
  expect(screen.queryByText(/standard that could be checked was met/)).toBeNull();
});

it("places Minor issues after Not met and before Met and not applicable", async () => {
  const minor = { ...findings[1]!, rule_id: PLAIN, verdict: "fail" as const, severity: "minor" };
  const blocking = { ...findings[1]!, verdict: "fail" as const };
  const pack = {
    ...resolvedPack,
    rules: [
      ...resolvedPack.rules,
      { ...resolvedPack.rules[0]!, id: PLAIN, title: "Plain words", severity: "minor" as const },
      { ...resolvedPack.rules[0]!, id: "icd203.as.5", title: "Dated", severity: "major" as const },
    ],
  };
  const passing = { ...findings[1]!, rule_id: "icd203.as.5", severity: "major" };
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () =>
      HttpResponse.json([blocking, findings[2]!, minor, passing]),
    ),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(pack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  await screen.findByRole("list", { name: "Not met" });
  expect(groupNames()).toEqual(["Not met", "Minor issues", "Met and not applicable", "Advisory"]);
});

it("counts as not met exactly the latest blocking and major fails", () => {
  const minor = { ...findings[1]!, rule_id: PLAIN, verdict: "fail" as const, severity: "minor" };
  const groups = standardsGroups(auditRows([...findings, minor], resolvedPack.rules));
  expect(groups.notMet.map((r) => r.ruleId)).toEqual([]);
  expect(groups.minor.map((r) => r.ruleId)).toEqual([PLAIN]);
  const major = { ...minor, severity: "major" };
  const again = standardsGroups(auditRows([...findings, major], resolvedPack.rules));
  expect(again.notMet.map((r) => r.ruleId)).toEqual([PLAIN]);
  expect(again.minor).toEqual([]);
});

it("marks an incomplete check's reason as the engine's own text", async () => {
  const line = "audit incomplete after 2 attempts: auditor: the audit reply was not JSON";
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
  );
  renderWithClient(<AuditTab runId={RUN_ID} degradations={[line]} />);
  const note = await screen.findByText(/^The standards check didn't finish:/);
  expect(note.querySelector("[data-raw-error]")).toHaveTextContent(
    "auditor: the audit reply was not JSON",
  );
  // our words around the reason pass the guard; the reason itself is the engine's
  expectNoEngineWords(document.body, { exceptRawErrors: true });
  expect(() => expectNoEngineWords(document.body)).toThrow();
});
