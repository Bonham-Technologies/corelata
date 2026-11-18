import { act, render, screen } from "@testing-library/react";
import { reportHtml } from "../../test/fixtures";
import { resetThemeForTests, setThemeChoice } from "../../theme/theme";
import {
  bridgeScript,
  HIGHLIGHT_CSS,
  installFrameBridge,
  withBridge,
  type HostToFrame,
} from "./frameBridge";
import { ReportFrame } from "./ReportFrame";

// M18 spec §5.5, R-M18-2, R-M18-10: the report follows the app's theme, not the computer's.

beforeEach(() => {
  localStorage.clear();
  resetThemeForTests();
});

function install(theme?: string) {
  const doc = new DOMParser().parseFromString(reportHtml, "text/html");
  let handler: ((message: HostToFrame) => void) | undefined;
  installFrameBridge(
    doc,
    () => {},
    (h) => (handler = h),
    HIGHLIGHT_CSS,
    "n",
    theme,
  );
  return { root: doc.documentElement, send: (m: unknown) => handler!(m as HostToFrame) };
}

it("styles the report's colour scheme by a class the bridge sets, inside the nonce's style", () => {
  expect(HIGHLIGHT_CSS).toContain(":root.corelata-theme-light { color-scheme: light; }");
  expect(HIGHLIGHT_CSS).toContain(":root.corelata-theme-dark { color-scheme: dark; }");
  const { root, send } = install("dark");
  expect(root.className).toBe("corelata-theme-dark"); // from the first paint
  send({ type: "corelata:theme", theme: "light" });
  expect(root.className).toBe("corelata-theme-light");
  send({ type: "corelata:theme", theme: "purple" });
  expect(root.className).toBe("corelata-theme-light"); // anything else is ignored
  expect(install().root.className).toBe(""); // no theme given: the report's own rule applies
});

it("builds the frame in a given theme, and leaves the document as before without one", () => {
  expect(bridgeScript("n", "dark")).toContain(
    `${JSON.stringify(HIGHLIGHT_CSS)}, "n", "dark");</script>`,
  );
  expect(withBridge(reportHtml, "n", "light")).toContain(`"n", "light");</script>`);
  expect(withBridge(reportHtml, "n")).toContain(`, "n");</script>`);
});

function frame(): HTMLIFrameElement {
  return screen.getByTitle("Report") as HTMLIFrameElement;
}

function ready() {
  const event = new MessageEvent("message", { data: { type: "corelata:ready" } });
  Object.defineProperty(event, "source", { value: frame().contentWindow });
  act(() => {
    window.dispatchEvent(event);
  });
}

const themeMessages = (post: { mock: { calls: unknown[][] } }) =>
  post.mock.calls.map(([m]) => m).filter((m) => (m as HostToFrame).type === "corelata:theme");

it("opens the frame in the app's theme and tells it when the theme changes", () => {
  setThemeChoice("dark");
  render(<ReportFrame html={reportHtml} selectedClaim={null} onSelectClaim={() => {}} />);
  expect(frame().getAttribute("srcdoc")).toContain('"dark");</script>');
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  ready();
  expect(themeMessages(post)).toEqual([]); // it already shows the dark theme
  act(() => setThemeChoice("light"));
  expect(themeMessages(post)).toEqual([{ type: "corelata:theme", theme: "light" }]);
  expect(frame().getAttribute("srcdoc")).toContain('"dark");</script>'); // not rebuilt
});

it("tells a frame that reloaded after a change which theme to show", () => {
  setThemeChoice("light");
  const { rerender } = render(
    <ReportFrame html={reportHtml} selectedClaim={null} onSelectClaim={() => {}} />,
  );
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  ready();
  act(() => setThemeChoice("dark"));
  rerender(
    <ReportFrame html={reportHtml + "<!-- v2 -->"} selectedClaim={null} onSelectClaim={() => {}} />,
  );
  ready(); // the new document was built in the first theme, light
  expect(themeMessages(post)).toEqual([
    { type: "corelata:theme", theme: "dark" },
    { type: "corelata:theme", theme: "dark" },
  ]);
});
