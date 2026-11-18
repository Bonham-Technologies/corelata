import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { reportHtml } from "../../test/fixtures";
import { ReportFrame } from "./ReportFrame";

function Host({ initial = null, html = reportHtml }: { initial?: string | null; html?: string }) {
  const [claim, setClaim] = useState<string | null>(initial);
  return (
    <>
      <output aria-label="Selected">{claim ?? "none"}</output>
      <ReportFrame html={html} selectedClaim={claim} onSelectClaim={setClaim} />
    </>
  );
}

function frame(): HTMLIFrameElement {
  return screen.getByTitle("Report") as HTMLIFrameElement;
}

/** A message as the page receives it; `source` is read-only on a real event, so it is defined. */
function deliver(data: unknown, source: Window | null = frame().contentWindow) {
  const event = new MessageEvent("message", { data });
  Object.defineProperty(event, "source", { value: source });
  act(() => {
    window.dispatchEvent(event);
  });
}

const highlight = (claim: string | null, scroll: boolean) => ({
  type: "corelata:highlight",
  claim,
  scroll,
});

it("puts the report and the bridge into a scriptable frame with no origin and its own policy", () => {
  render(<Host initial="c3" />);
  expect(frame()).toHaveAttribute("sandbox", "allow-scripts");
  const srcdoc = frame().getAttribute("srcdoc")!;
  expect(srcdoc).toContain("Varna Port Expansion");
  expect(srcdoc).toContain("corelata:highlight");
  expect(srcdoc.indexOf("<script")).toBeLessThan(srcdoc.lastIndexOf("</body>"));
  const policy = /nonce-([A-Za-z0-9+/=]+)'/.exec(srcdoc)![1];
  const onScript = /<script nonce="([^"]+)">/.exec(srcdoc)![1];
  expect(policy).toBe(onScript); // puts the same nonce in the policy and on the bridge
  expect(srcdoc.indexOf('<meta http-equiv="Content-Security-Policy"')).toBeLessThan(
    srcdoc.indexOf("<script"),
  );
  expect(document.querySelector("style")).toBeNull(); // the report's stylesheet stays inside
});

it("sends the selection once the frame is ready, then on every change", () => {
  render(<Host initial="c3" />);
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  expect(post).not.toHaveBeenCalled(); // nothing before the frame reports in
  deliver({ type: "corelata:ready" });
  expect(post).toHaveBeenLastCalledWith(highlight("c3", true), "*");
  deliver({ type: "corelata:select", claim: "c1" }); // a click inside the frame: no scroll
  expect(screen.getByLabelText("Selected")).toHaveTextContent("c1");
  expect(post).toHaveBeenLastCalledWith(highlight("c1", false), "*");
  deliver({ type: "corelata:select", claim: "c1" }); // the same claim again: nothing changes
  expect(post).toHaveBeenCalledTimes(2);
});

it("clears the highlight when the selection is cleared", () => {
  const { rerender } = render(
    <ReportFrame html={reportHtml} selectedClaim="c3" onSelectClaim={() => {}} />,
  );
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  deliver({ type: "corelata:ready" });
  rerender(<ReportFrame html={reportHtml} selectedClaim={null} onSelectClaim={() => {}} />);
  expect(post).toHaveBeenCalledTimes(2);
  expect(post).toHaveBeenLastCalledWith(highlight(null, true), "*");
});

it("re-sends the highlight after a new report loads", () => {
  const { rerender } = render(
    <ReportFrame html={reportHtml} selectedClaim="c3" onSelectClaim={() => {}} />,
  );
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  deliver({ type: "corelata:ready" });
  rerender(
    <ReportFrame html={reportHtml + "<!-- v2 -->"} selectedClaim="c3" onSelectClaim={() => {}} />,
  );
  expect(frame().getAttribute("srcdoc")).toContain("<!-- v2 -->");
  deliver({ type: "corelata:ready" }); // the reloaded frame's bridge reports in
  expect(post).toHaveBeenCalledTimes(2);
  expect(post).toHaveBeenLastCalledWith(highlight("c3", true), "*");
});

it("ignores messages from other windows and malformed data", () => {
  render(<Host />);
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  deliver({ type: "corelata:ready" }, window);
  deliver({ type: "corelata:select", claim: "c1" }, null);
  deliver(null);
  deliver("corelata:select");
  deliver({ type: "corelata:select", claim: 42 });
  deliver({ type: "corelata:select", claim: "" });
  deliver({ type: "corelata:select", claim: "x".repeat(201) });
  expect(post).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Selected")).toHaveTextContent("none");
});
