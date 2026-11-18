import { useEffect, useId, useRef, useState } from "react";
import { ApiError, errorText } from "../../api/client";
import { useUploadSource } from "../../api/projects";
import type { SourceKind, SourceView } from "../../api/types";
import { messageOf } from "../../components/ErrorMessage";

/** The file types the API parses (spec §5): the engine's built-in ingestors' extensions.
 * engine/tests/ingest/test_registry.py reads this declaration and pins it to the registry
 * (CRL-109), so keep it an `export const ACCEPTED = [...]` of double-quoted strings. */
export const ACCEPTED = [
  ".docx",
  ".pdf",
  ".txt",
  ".md",
  ".markdown",
  ".html",
  ".htm",
  ".xhtml",
  ".json",
  ".csv",
];

const MB = 1024 * 1024;

/** Coglossa's sizeText (translate/DropArea.tsx). */
export function sizeText(bytes: number): string {
  if (bytes < MB) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / MB).toFixed(1).replace(/\.0$/, "")} MB`;
}

/** What is wrong with a file before it is sent, or null (M18 spec §5.2). */
export function fileProblem(file: File, maxMb: number): string | null {
  const dot = file.name.lastIndexOf(".");
  if (dot < 0 || !ACCEPTED.includes(file.name.slice(dot).toLowerCase())) {
    return `${file.name} isn't a file type Corelata reads (${ACCEPTED.join(" ")}).`;
  }
  if (file.size > maxMb * MB) {
    return `${file.name} is ${sizeText(file.size)}, and the limit is ${maxMb} MB.`;
  }
  return null;
}

/** Why one upload failed, in one line: the API's own (its 413 names the limit), or, for a 413
 * that came without one (a proxy's limit), "too large for this server" (R-M18-11). */
export function uploadErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 413 && error.message === errorText(413, null)) {
    return "too large for this server";
  }
  return messageOf(error);
}

type Chosen = { key: number; file: File; uploading: boolean; error: string | null };

let counter = 0;

/** Adapted from Coglossa's DropArea (M18 spec §5.2): files by drag and drop or by browsing, as
 * chips; Upload sends them one after another, one request each, as the API takes them. A file
 * that fails keeps its chip with the reason and Try again; the others carry on. */
export function AddSources({
  projectId,
  maxUploadMb,
  onAdded,
  onDone,
}: {
  projectId: string;
  maxUploadMb: number;
  onAdded: (added: SourceView[]) => void;
  /** Called when an Upload has finished and at least one file went up (the button has gone
   * quiet by then, so the page moves focus on). */
  onDone?: () => void;
}) {
  const upload = useUploadSource(projectId);
  const [kind, setKind] = useState<SourceKind>("file");
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  // An upload still running when the project changes (this component is keyed by the project,
  // so it unmounts) must not hand its sources to the next project's page.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // Chips removed by the analyst; a queued file removed during an upload is skipped by `send`.
  const removed = useRef(new Set<number>());
  const inputId = useId();
  const kindId = useId();
  const sendable = chosen.filter((c) => fileProblem(c.file, maxUploadMb) === null);

  function add(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (files.length === 0) return;
    setChosen((current) => [
      ...current,
      ...files.map((file) => ({ key: ++counter, file, uploading: false, error: null })),
    ]);
  }

  function patch(key: number, change: Partial<Chosen>) {
    setChosen((current) => current.map((c) => (c.key === key ? { ...c, ...change } : c)));
  }

  async function send(items: Chosen[]) {
    setBusy(true);
    let sent = false;
    for (const item of items) {
      if (!alive.current) return;
      if (removed.current.has(item.key)) continue;
      patch(item.key, { uploading: true, error: null });
      try {
        const added = await upload.mutateAsync({ file: item.file, kind });
        if (!alive.current) return;
        setChosen((current) => current.filter((c) => c.key !== item.key));
        onAdded(added);
        sent = true;
      } catch (error) {
        if (!alive.current) return;
        patch(item.key, { uploading: false, error: uploadErrorText(error) });
      }
    }
    if (alive.current) {
      setBusy(false);
      if (sent) onDone?.();
    }
  }

  return (
    <div className="add-sources">
      <h3>Add sources</h3>
      <div className="drop">
        <label
          htmlFor={inputId}
          className={over ? "drop-area over" : "drop-area"}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            add(event.dataTransfer.files);
          }}
        >
          <strong>Drop files here, or click to choose</strong>
          <span className="muted">
            {ACCEPTED.join(" ")} · up to {maxUploadMb} MB each
          </span>
        </label>
        <input
          id={inputId}
          type="file"
          multiple
          accept={ACCEPTED.join(",")}
          aria-label="Choose files"
          className="visually-hidden"
          onChange={(event) => {
            add(event.target.files);
            event.target.value = ""; // the same file can be chosen again
          }}
        />
      </div>
      <ul aria-label="Chosen files" className="chips">
        {chosen.map((c) => {
          const problem = fileProblem(c.file, maxUploadMb);
          const why = problem ?? (c.error ? `${c.file.name}: ${c.error}` : null);
          return (
            <li key={c.key} className={why ? "chip bad" : "chip"} aria-busy={c.uploading}>
              <span dir="auto">{c.file.name}</span>{" "}
              <span className="muted">{sizeText(c.file.size)}</span>
              {c.uploading ? <span className="muted"> uploading…</span> : null}
              {why ? (
                <span role="alert" className="error" dir="auto">
                  {why}
                </span>
              ) : null}
              {c.error ? (
                <button
                  type="button"
                  aria-label={`Try again: ${c.file.name}`}
                  onClick={() => void send([c])}
                  disabled={busy}
                >
                  Try again
                </button>
              ) : null}
              <button
                type="button"
                className="quiet"
                aria-label={`Remove ${c.file.name}`}
                disabled={c.uploading}
                onClick={() => {
                  removed.current.add(c.key);
                  setChosen((current) => current.filter((x) => x.key !== c.key));
                }}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
      <div className="row">
        <label htmlFor={kindId}>Add as</label>
        <select id={kindId} value={kind} onChange={(e) => setKind(e.target.value as SourceKind)}>
          <option value="file">Documents</option>
          <option value="coglossa_export">Coglossa exports</option>
        </select>
        <button
          type="button"
          onClick={() => void send(sendable.filter((c) => c.error === null))}
          disabled={busy || sendable.every((c) => c.error !== null)}
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
