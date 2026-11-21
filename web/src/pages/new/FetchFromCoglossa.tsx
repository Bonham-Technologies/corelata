import { useEffect, useId, useRef, useState } from "react";
import { useFromCoglossa } from "../../api/projects";
import type { SourceView } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";

export function FetchFromCoglossa({
  projectId,
  onAdded,
}: {
  projectId: string;
  onAdded: (added: SourceView[]) => void;
}) {
  const fetchRun = useFromCoglossa(projectId);
  const [runId, setRunId] = useState("");
  // Set when the project had the run's export already: nothing was added (CRL-126).
  const [note, setNote] = useState<string | null>(null);
  const id = useId();
  // A fetch still running when the project changes (this component is keyed by the project, so
  // it unmounts) must not hand its sources to the next project's page, as in AddSources.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const asked = runId.trim();
    try {
      const added = await fetchRun.mutateAsync(asked);
      if (!alive.current) return;
      setRunId("");
      if (added[0]?.already_in_project) {
        setNote(`Coglossa run ${asked} is already in this project as ${added[0].name}.`);
        return;
      }
      onAdded(added);
    } catch {
      // the mutation's error is shown below
    }
  }

  return (
    <form
      aria-label="Import from Coglossa"
      className="row"
      onSubmit={(event) => void submit(event)}
    >
      <label htmlFor={id} className="muted">
        Coglossa run id
      </label>
      <input
        id={id}
        value={runId}
        onChange={(event) => {
          setRunId(event.target.value);
          setNote(null);
        }}
      />
      <button type="submit" disabled={!runId.trim() || fetchRun.isPending}>
        {fetchRun.isPending ? "Fetching…" : "Fetch from Coglossa"}
      </button>
      {fetchRun.error ? <ErrorMessage error={fetchRun.error} /> : null}
      {note ? (
        <p role="status" className="muted" dir="auto">
          {note}
        </p>
      ) : null}
    </form>
  );
}
