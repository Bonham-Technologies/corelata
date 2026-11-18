import { readFileSync } from "node:fs";
import {
  CLAIM_KIND,
  citedByText,
  degradationText,
  plural,
  PROGRESS_STEPS,
  reportStatusText,
  SEVERITY,
  severityText,
  STEP_LABEL,
  VERDICT,
} from "./words";

// The API's own list of every value it can send (tests run from web/): a value the engine adds
// later fails here before it reaches a screen as a bare engine word (M18 spec §4).
const schemas = (
  JSON.parse(readFileSync("../schema/openapi.json", "utf8")) as {
    components: { schemas: Record<string, { enum?: string[] }> };
  }
).components.schemas;
const values = (name: string) => schemas[name]!.enum!;

it.each([
  ["RunState", STEP_LABEL],
  ["Verdict", VERDICT],
  ["Severity", SEVERITY],
  ["ClaimKind", CLAIM_KIND],
] as const)("has a word for every %s the API can send", (name, words) => {
  expect(Object.keys(words).sort()).toEqual([...values(name)].sort());
});

it("lists the writing steps in the pipeline's order, from waiting to ready", () => {
  expect(PROGRESS_STEPS.map((s) => STEP_LABEL[s])).toEqual([
    "Waiting to start",
    "Reading the sources",
    "Checking the value statement",
    "Drafting",
    "Editing for the reader",
    "Checking against the standards",
    "Preparing the documents",
    "Ready to review",
  ]);
});

it("says where a claim is cited in the reader's words, and keeps an unknown path", () => {
  expect(citedByText("key_judgments[0]")).toBe("Key judgments, item 1");
  expect(citedByText("analysis[0].paragraphs[1]")).toBe("Analysis, section 1, paragraph 2");
  expect(citedByText("alternatives[2]")).toBe("Alternatives, item 3");
  expect(citedByText("appendix.x")).toBe("appendix.x");
});

it("words a degradation in both forms, keeps the engine's error, and keeps any other line", () => {
  expect(degradationText("conveyance skipped after 2 attempts: conveyor: bad JSON")).toEqual({
    text: "Editing for the reader was skipped after 2 attempts.",
    detail: "conveyor: bad JSON",
  });
  expect(degradationText("audit incomplete after 1 attempt: auditor: timeout")).toEqual({
    text: "The standards check didn't finish after 1 attempt.",
    detail: "auditor: timeout",
  });
  expect(degradationText("something new")).toEqual({ text: "something new", detail: null });
  expect(degradationText("audit incomplete")).toEqual({ text: "audit incomplete", detail: null });
});

it("words a report's status", () => {
  expect(reportStatusText("clean", 0)).toBe("Meets the standards");
  expect(reportStatusText("findings_open", 1)).toBe("1 standard not met");
  expect(reportStatusText("findings_open", 3)).toBe("3 standards not met");
  expect(reportStatusText("findings_open", 0)).toBe("Checked in part");
  expect(plural(2, "passage")).toBe("2 passages");
});

it("capitalises a finding's severity, a pack's own word too", () => {
  expect(severityText("blocking")).toBe("Blocking");
  expect(severityText("critical")).toBe("Critical");
});
