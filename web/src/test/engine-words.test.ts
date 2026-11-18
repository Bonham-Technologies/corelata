import { DISCOVERY_STALLED } from "../api/discoveries";
import { engineWordsOn, expectNoEngineWords, visiblePrimaryButtons } from "./engine-words";

function page(html: string): HTMLElement {
  const root = document.createElement("main");
  root.innerHTML = html;
  return root;
}

it("fires on an engine word in the text and in every worded attribute", () => {
  expect(engineWordsOn(page("<p>a rerun</p>"))).toEqual(["rerun"]);
  expect(engineWordsOn(page('<input placeholder="gate" />'))).toEqual(["gate"]);
  expect(engineWordsOn(page('<span title="the audit">x</span>'))).toEqual(["audit"]);
  expect(engineWordsOn(page('<img alt="a finding" />'))).toEqual(["finding"]);
  expect(engineWordsOn(page('<div aria-description="evidence units"></div>'))).toEqual([
    "evidence units",
  ]);
  expect(engineWordsOn(page('<button aria-label="Discovery">x</button>'))).toEqual(["Discovery"]);
  expect(() => expectNoEngineWords(page("<p>the pack</p>"))).toThrow();
});

it("lets through exactly 'Coglossa run' and the discovery's limit messages, and nothing wider", () => {
  expect(engineWordsOn(page("<p>Coglossa run 42</p>"))).toEqual([]);
  expect(engineWordsOn(page("<p>Coglossa run run-42</p>"))).toEqual([]);
  expect(engineWordsOn(page("<label>Coglossa run id</label>"))).toEqual([]);
  expect(engineWordsOn(page("<p>Coglossa run rerun</p>"))).toEqual(["run", "rerun"]);
  expect(engineWordsOn(page("<p>Coglossa runs and a run</p>"))).toEqual(["runs", "run"]);
  expect(engineWordsOn(page("<p>Coglossa reruns</p>"))).toEqual(["reruns"]);
  const messages = [
    "Discovery did not start within 60 minutes and was stopped: the worker was stopped or busy with runs. Start a new discovery.",
    "Discovery did not finish within 10 minutes and was stopped. Start a new discovery.",
    DISCOVERY_STALLED,
  ];
  for (const message of messages) expect(engineWordsOn(page(`<p>${message}</p>`))).toEqual([]);
  expect(engineWordsOn(page("<p>Start a new discovery.</p>"))).toEqual(["discovery"]);
});

it("lets through a Coglossa locator with a run id, and no wider", () => {
  expect(engineWordsOn(page("<p>coglossa:run-42/para:3</p>"))).toEqual([]);
  expect(engineWordsOn(page("<p>coglossa:audit</p>"))).toEqual(["audit"]);
  expect(engineWordsOn(page("<p>coglossa:audit/run</p>"))).toEqual(["audit", "run"]);
  expect(engineWordsOn(page("<p>Coglossa:run-42/x</p>"))).toEqual(["run"]);
  // the allowance stops at the run id's segment: engine words after the slash are still caught
  expect(engineWordsOn(page("<p>coglossa:run-42/audit</p>"))).toEqual(["audit"]);
  expect(engineWordsOn(page("<p>coglossa:run-42/para:3 and the pack</p>"))).toEqual(["pack"]);
});

it("skips only what is marked as the engine's own error text", () => {
  const marked = page("<p>Failed: <span data-raw-error>conveyor: bad</span></p>");
  expect(() => expectNoEngineWords(marked, { exceptRawErrors: true })).not.toThrow();
  expect(() => expectNoEngineWords(marked)).toThrow();
  const other = page("<p>the audit <span data-raw-error>conveyor: bad</span></p>");
  expect(() => expectNoEngineWords(other, { exceptRawErrors: true })).toThrow();
});

it("lets through the Settings button's label, and not a run beside it", () => {
  expect(engineWordsOn(page("<button>Run a full check</button>"))).toEqual([]);
  expect(engineWordsOn(page('<button aria-label="Run a full check">x</button>'))).toEqual([]);
  expect(engineWordsOn(page("<p>a run</p>"))).toEqual(["run"]);
  expect(engineWordsOn(page("<p>Run a full check of the run</p>"))).toEqual(["run"]);
});

it("counts a primary button a person can see, including one in a closed <details>'s <summary>", () => {
  const root = page(
    '<button class="primary">a</button>' +
      '<details><summary><button class="primary">b</button></summary>' +
      '<button class="primary">c</button></details>' +
      '<details open><button class="primary">d</button></details>' +
      '<details><summary>s</summary><details><summary><button class="primary">e</button>' +
      "</summary></details></details>" +
      '<dialog><button class="primary">f</button></dialog>' +
      '<div hidden><a class="button primary">g</a></div>',
  );
  expect(visiblePrimaryButtons(root).map((el) => el.textContent)).toEqual(["a", "b", "d"]);
});
