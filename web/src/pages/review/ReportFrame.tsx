import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "../../theme/theme";
import { type FrameToHost, type HostToFrame, withBridge } from "./frameBridge";

/** The rendered report (spec §9, claim ids on) in a sandboxed frame with no origin of its own:
 * its stylesheet stays inside, nothing in it can touch the page, and the bridge script in the
 * document is the only channel (M7). The document carries its own Content-Security-Policy (M9).
 * The page tells the frame which claim to highlight and which theme to show (M18 spec §5.5); the
 * frame tells the page which cited element a reader clicked. */
export function ReportFrame({
  html,
  selectedClaim,
  onSelectClaim,
}: {
  html: string;
  selectedClaim: string | null;
  onSelectClaim: (claimId: string) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const select = useRef(onSelectClaim);
  const fromFrame = useRef(false); // the last selection came from a click inside the frame
  const current = useRef(selectedClaim);
  const { theme } = useTheme();
  // The frame is built with the theme the page had first, so it opens in it; a later change is
  // a message, not a new document (R-M18-10). `shown` is the theme the frame shows now.
  const [builtWith] = useState(theme);
  const shown = useRef(builtWith);
  // The message handler reads the latest callback and selection; they are copied after each
  // render commits (refs are not written during render) and before any later message arrives.
  useLayoutEffect(() => {
    select.current = onSelectClaim;
    current.current = selectedClaim;
  });
  const [ready, setReady] = useState(0); // bumps each time a loaded frame's bridge reports in
  const srcdoc = useMemo(() => withBridge(html, undefined, builtWith), [html, builtWith]);

  useEffect(() => {
    const onMessage = (event: MessageEvent<FrameToHost | null>) => {
      if (!event.source || event.source !== frame.current?.contentWindow) return;
      const message = event.data;
      if (typeof message !== "object" || message === null) return;
      if (message.type === "corelata:ready") {
        shown.current = builtWith; // a (re)loaded frame starts in the theme it was built with
        setReady((n) => n + 1);
      } else if (
        message.type === "corelata:select" &&
        typeof message.claim === "string" &&
        message.claim.length > 0 &&
        message.claim.length <= 200 // a hostile in-frame script cannot push junk into the URL
      ) {
        fromFrame.current = message.claim !== current.current;
        select.current(message.claim);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [builtWith]);

  // The highlight follows the selection, once there is a frame to tell.
  useEffect(() => {
    if (!ready) return;
    const message: HostToFrame = {
      type: "corelata:highlight",
      claim: selectedClaim,
      scroll: !fromFrame.current,
    };
    frame.current?.contentWindow?.postMessage(message, "*"); // the frame has no origin to name
    fromFrame.current = false;
  }, [selectedClaim, ready]);

  // The frame follows the app's theme: on a change, and on a frame that reloaded after one.
  useEffect(() => {
    if (!ready || theme === shown.current) return;
    const message: HostToFrame = { type: "corelata:theme", theme };
    frame.current?.contentWindow?.postMessage(message, "*");
    shown.current = theme;
  }, [theme, ready]);

  return (
    <iframe
      ref={frame}
      title="Report"
      className="report-frame"
      sandbox="allow-scripts"
      srcDoc={srcdoc}
    />
  );
}
