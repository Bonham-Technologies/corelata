// Copied from Coglossa unchanged (spec §2.2).
const ACTIVATABLE = "button, a[href], summary, [role=button], input";
const NOT_TEXT_INPUT = ["checkbox", "radio", "button", "submit", "reset", "image", "file"];

/** Keys aimed at a control belong to that control: every key while typing in a text field,
 * and Enter or Space on something that activates (a button, link, checkbox). Other keys,
 * such as n, p and Escape, still work after a mouse click leaves focus on a button. */
export function keyBelongsToControl(target: EventTarget | null, key: string): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.closest("textarea, select, [contenteditable]")) {
    return true;
  }
  const input = target.closest("input");
  if (input && !NOT_TEXT_INPUT.includes(input.type)) return true;
  return (key === "Enter" || key === " ") && target.closest(ACTIVATABLE) !== null;
}
