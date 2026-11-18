import { type Ref, useEffect, useId, useRef } from "react";
import { useSearchParams } from "react-router";
import { useUpdateSearchParams } from "../../lib/searchParams";
import { useStartDiscovery } from "../../api/discoveries";
import { CharCount, nearLimit } from "../../components/CharCount";
import { ErrorMessage } from "../../components/ErrorMessage";
import { VALUE_STATEMENT_MAX_LENGTH } from "../../lib/limits";
import { Suggestions } from "./Suggestions";

/** `ref`: the statement's field, for the page to focus. `error`: why the form could not be
 * filled from an earlier run, shown by the field it would have filled (CRL-108). A statement
 * set by the page rather than typed (a draft, an earlier run) can be over the limit, which the
 * field's maxLength does not trim; the field then says to shorten it (CRL-108). */
export function ValueStatement({
  projectId,
  sourceIds,
  value,
  onChange,
  error,
  ref,
}: {
  projectId: string;
  sourceIds: string[];
  value: string;
  onChange: (value: string) => void;
  error?: unknown;
  ref?: Ref<HTMLTextAreaElement>;
}) {
  const start = useStartDiscovery();
  // The discovery lives in the URL, so a reload reads it again instead of forgetting it
  // (R-M16-14); replace, so Back does not step through earlier discoveries. The page's writer
  // applies it to the URL as the page's other writes left it (CRL-62).
  const [params] = useSearchParams();
  const update = useUpdateSearchParams();
  const discoveryId = params.get("discovery");
  const id = useId();
  const countId = useId();
  const tooLongId = useId();
  const tooLong = value.length > VALUE_STATEMENT_MAX_LENGTH;
  const heading = useRef<HTMLHeadingElement>(null);
  const focusHeading = useRef(false);
  const canSuggest = sourceIds.length > 0 && !start.isPending;

  function setDiscoveryId(value: string | null) {
    update(
      (now) => {
        if (value) now.set("discovery", value);
        else now.delete("discovery");
        return now;
      },
      { replace: true },
    );
  }

  // Suggest value disables while it starts; the Suggestions heading takes focus when they appear,
  // not when a reload reads a discovery from the URL.
  useEffect(() => {
    if (focusHeading.current && discoveryId && heading.current) {
      focusHeading.current = false;
      heading.current.focus();
    }
  }, [discoveryId]);

  function suggest() {
    setDiscoveryId(null);
    start.mutate(
      // no audience hint: the screen has no field for one, so the field is left out (R-M17-6)
      { project_id: projectId, source_ids: sourceIds },
      {
        onSuccess: (view) => {
          focusHeading.current = true;
          setDiscoveryId(view.discovery_id);
        },
      },
    );
  }

  return (
    <section aria-label="Value statement" className="card">
      <div className="field">
        <label htmlFor={id}>Value statement</label>
        <textarea
          ref={ref}
          id={id}
          rows={3}
          value={value}
          dir="auto"
          placeholder="What this report must establish for its reader"
          maxLength={VALUE_STATEMENT_MAX_LENGTH}
          aria-describedby={
            tooLong
              ? `${countId} ${tooLongId}`
              : nearLimit(value, VALUE_STATEMENT_MAX_LENGTH)
                ? countId
                : undefined
          }
          aria-invalid={tooLong || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        <CharCount id={countId} value={value} max={VALUE_STATEMENT_MAX_LENGTH} />
        {tooLong ? (
          <p id={tooLongId} className="error">
            Shorten the statement to write the report.
          </p>
        ) : null}
        {error ? <ErrorMessage error={error} /> : null}
      </div>
      <div className="row">
        <button type="button" onClick={suggest} disabled={!canSuggest}>
          Suggest value
        </button>
        {sourceIds.length === 0 ? (
          <span className="muted">Select at least one source to get suggestions.</span>
        ) : null}
      </div>
      {start.error ? <ErrorMessage error={start.error} /> : null}
      {discoveryId ? (
        <>
          <h2 ref={heading} tabIndex={-1}>
            Suggestions
          </h2>
          <Suggestions discoveryId={discoveryId} onPick={onChange} />
        </>
      ) : null}
    </section>
  );
}
