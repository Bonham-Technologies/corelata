import { DISCOVERY_STALLED } from "../api/discoveries";

/** The engine's words that must not reach the main flow (M18 spec §4, success criterion 4,
 * R-M18-14). */
export const ENGINE_WORDS =
  /\b(runs?|reruns?|discovery|discoveries|gate|gating|audit(s|ing)?|conveyor|conveying|conveyed|ingesting|iterations?|verdicts?|evidence units?|findings?|digested|pack)\b/i;

/** What may stay, and nothing else:
 * - "Coglossa run" is Coglossa's word for its own run (§5.2), exactly that phrase and only as
 *   "Coglossa run <id>" (an id has a digit in it) or the field "Coglossa run id".
 * - A Coglossa locator ("coglossa:<run id>/…") is shown as it is (§4.1): the run is Coglossa's.
 *   Only the "coglossa:<run id>/" part is let through; what follows the slash is still checked.
 * - The discovery's limit messages are the server's texts and the page's pinned fallback, agreed
 *   with the owner in M16 and M17 (R-M16-2, R-M17-28). Each is listed in full, not as a word. */
const ALLOWED: RegExp[] = [
  // Settings' button, in the spec's words (§5.6): "Run" is the English verb there, not the engine's run.
  /\bRun a full check\b/g,
  /\bCoglossa run (?:id\b|(?=\S*\d)\S+)/gi,
  /\bcoglossa:(?=[^\s/]*\d)[^\s/]+\//g,
  /Discovery did not start within [^:]+ and was stopped: the worker was stopped or busy with runs\. Start a new discovery\./g,
  /Discovery did not finish within [^.]+ and was stopped\. Start a new discovery\./g,
  new RegExp(DISCOVERY_STALLED.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"),
];

/** The attributes whose values a reader meets: a name, a hint, a tooltip, an image's text. */
const WORDED = ["aria-label", "aria-description", "placeholder", "title", "alt"];

/** The page's visible words: its text, and the words in its labels, hints, tooltips and image
 * text, so a reworded heading cannot hide an engine word in an attribute. */
export function screenWords(root: HTMLElement): string {
  const selector = WORDED.map((name) => `[${name}]`).join(",");
  const attributes = [root, ...root.querySelectorAll(selector)].flatMap((el) =>
    WORDED.map((name) => el.getAttribute(name)).filter((v): v is string => v !== null),
  );
  // text node by text node, so neighbouring elements do not run into one word
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: string[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    texts.push(node.textContent ?? "");
  }
  return [...texts, ...attributes].join(" \n ");
}

/** The words that would trip the guard: the screen's words minus the allowed phrases. */
export function engineWordsOn(root: HTMLElement): string[] {
  const words = ALLOWED.reduce((text, allowed) => text.replace(allowed, " "), screenWords(root));
  return [...words.matchAll(new RegExp(ENGINE_WORDS, "gi"))].map((m) => m[0]);
}

/** Whether `el` is hidden by a closed `<details>`: inside one, and not in that one's own
 * `<summary>`, which a closed `<details>` still shows. */
function inClosedDetails(el: Element): boolean {
  for (let at: Element | null = el; at; at = at.parentElement) {
    const details = at.parentElement;
    if (details?.matches("details:not([open])")) {
      const ownSummary = at.matches("summary") && details.querySelector(":scope > summary") === at;
      if (!ownSummary) return true;
    }
  }
  return false;
}

/** The primary buttons a person can see: not those in a closed dialog, nor under `[hidden]`,
 * nor in a closed `<details>` other than in its `<summary>`. */
export function visiblePrimaryButtons(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>("button.primary, a.button.primary")].filter(
    (el) => !el.closest("dialog:not([open]), [hidden]") && !inClosedDetails(el),
  );
}

/** `exceptRawErrors`: leave out the elements marked `data-raw-error`. They show the engine's own
 * error text, on purpose, so the analyst can pass it on; it is not a general exception and no
 * other element is skipped. */
export function expectNoEngineWords(
  root: HTMLElement,
  { exceptRawErrors = false }: { exceptRawErrors?: boolean } = {},
): void {
  let checked = root;
  if (exceptRawErrors) {
    checked = root.cloneNode(true) as HTMLElement;
    checked.querySelectorAll("[data-raw-error]").forEach((el) => el.remove());
  }
  expect(engineWordsOn(checked)).toEqual([]);
}
