import { DISCOVERY_STALLED, discoveryStalled, useDiscovery } from "../../api/discoveries";
import { ErrorMessage } from "../../components/ErrorMessage";
import { plural } from "../../lib/words";

export function Suggestions({
  discoveryId,
  onPick,
}: {
  discoveryId: string;
  onPick: (text: string) => void;
}) {
  const discovery = useDiscovery(discoveryId);
  const view = discovery.data;
  if (discovery.error) return <ErrorMessage error={discovery.error} />;
  if (discoveryStalled(view)) {
    // Polling has stopped (R-M16-2); role="status" is a polite live region.
    return (
      <p role="status" aria-label="Suggestions" className="muted">
        {DISCOVERY_STALLED}
      </p>
    );
  }
  if (view?.state === "created") {
    // queued behind reports, or no worker running: the server's start limit applies (R-M17-28)
    return (
      <p role="status" aria-label="Suggestions" className="muted">
        Waiting for Corelata to start looking…
      </p>
    );
  }
  if (!view || view.state === "running") {
    return (
      <p role="status" aria-label="Suggestions" className="muted">
        Looking for value in the selected sources…
      </p>
    );
  }
  if (view.state === "failed")
    return <ErrorMessage error={new Error(view.error ?? "No suggestions could be made.")} />;
  const candidates = view.candidates ?? [];
  if (candidates.length === 0)
    return <p className="muted">No value statement was found in these sources.</p>;
  return (
    <ul aria-label="Suggested value statements" className="suggestions">
      {candidates.map((c, i) => {
        const evidenceCount = (c.evidence ?? []).length;
        return (
          <li key={i}>
            <p dir="auto">
              <strong>{c.text}</strong>
            </p>
            <p className="muted">
              For <span dir="auto">{c.audience}</span> · {plural(evidenceCount, "passage")}
            </p>
            {c.confidence_note ? <p className="muted">{c.confidence_note}</p> : null}
            <button type="button" onClick={() => onPick(c.text)}>
              Use this statement
            </button>
          </li>
        );
      })}
    </ul>
  );
}
