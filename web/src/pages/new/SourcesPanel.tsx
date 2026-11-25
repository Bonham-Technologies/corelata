import { useEffect, useRef } from "react";
import { useInfo } from "../../api/system";
import { useSources } from "../../api/projects";
import type { SourceView } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { AddSources } from "./AddSources";
import { FetchFromCoglossa } from "./FetchFromCoglossa";
import { SourceDetails, statedText } from "./SourceDetails";

/** A source's kind in words: "TXT", or "Coglossa run 1234…" (M18 spec §5.2). */
export function kindText(source: SourceView): string {
  const coglossa = source.provenance["coglossa_run_id"];
  return typeof coglossa === "string" ? `Coglossa run ${coglossa}` : source.format.toUpperCase();
}

/** The project page's Sources card (M18 spec §5.2). */
export function SourcesPanel({
  projectId,
  selected,
  onToggle,
  onAdded,
}: {
  projectId: string;
  selected: ReadonlySet<string>;
  onToggle: (sourceId: string, on: boolean) => void;
  onAdded: (added: SourceView[]) => void;
}) {
  const info = useInfo();
  const sources = useSources(projectId);
  const list = sources.data ?? [];
  // After an Upload the button has no more to do; focus goes to the count of selected sources,
  // which says what the list now holds. It waits for the list when this is the first source.
  const status = useRef<HTMLParagraphElement>(null);
  const wantStatus = useRef(false);
  useEffect(() => {
    if (wantStatus.current && status.current) {
      wantStatus.current = false;
      status.current.focus();
    }
  });
  return (
    <section aria-label="Sources" className="card">
      <h2>Sources</h2>
      {sources.isPending ? <Loading what="Loading sources" /> : null}
      {sources.error ? <ErrorMessage error={sources.error} /> : null}
      {sources.data && list.length === 0 ? (
        <p className="muted">No sources yet. Add a file to begin.</p>
      ) : null}
      {list.length > 0 ? (
        <ul className="source-list">
          {list.map((s) => (
            <li key={s.id} className="row between">
              <label className="row">
                <input
                  type="checkbox"
                  aria-label={`Use ${s.name} in this report`}
                  checked={selected.has(s.id)}
                  onChange={(event) => onToggle(s.id, event.target.checked)}
                />
                <span dir="auto">{s.name}</span>
                <span className="badge">{kindText(s)}</span>
                {statedText(s) ? <span className="muted">{statedText(s)}</span> : null}
              </label>
              <SourceDetails projectId={projectId} source={s} />
            </li>
          ))}
        </ul>
      ) : null}
      {list.length > 0 ? (
        <p ref={status} tabIndex={-1} role="status" aria-label="Selected sources" className="muted">
          {list.filter((s) => selected.has(s.id)).length} of {list.length} selected
        </p>
      ) : null}
      <AddSources
        key={projectId}
        projectId={projectId}
        maxUploadMb={info.data?.max_upload_mb ?? 200}
        onAdded={onAdded}
        onDone={() => {
          wantStatus.current = true;
          status.current?.focus();
          if (status.current) wantStatus.current = false;
        }}
      />
      {info.data?.coglossa ? (
        <FetchFromCoglossa key={projectId} projectId={projectId} onAdded={onAdded} />
      ) : null}
    </section>
  );
}
