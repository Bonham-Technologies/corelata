import { keyBelongsToControl } from "./keys";

function el(html: string, selector: string): HTMLElement {
  document.body.innerHTML = html;
  return document.body.querySelector<HTMLElement>(selector)!;
}

it("leaves keys alone when the target is not an element", () => {
  expect(keyBelongsToControl(null, "n")).toBe(false);
  expect(keyBelongsToControl(document, "n")).toBe(false);
});

it("gives every key to text fields", () => {
  expect(keyBelongsToControl(el("<textarea></textarea>", "textarea"), "n")).toBe(true);
  expect(keyBelongsToControl(el("<input type=text />", "input"), "n")).toBe(true);
  expect(keyBelongsToControl(el("<div contenteditable='true'><b>x</b></div>", "b"), "n")).toBe(
    true,
  );
});

it("gives only Enter and Space to things that activate", () => {
  const button = el("<button>Go</button>", "button");
  expect(keyBelongsToControl(button, "Enter")).toBe(true);
  expect(keyBelongsToControl(button, " ")).toBe(true);
  expect(keyBelongsToControl(button, "n")).toBe(false);
  expect(keyBelongsToControl(el("<input type=checkbox />", "input"), "n")).toBe(false);
  expect(keyBelongsToControl(el("<p>text</p>", "p"), "Enter")).toBe(false);
});
