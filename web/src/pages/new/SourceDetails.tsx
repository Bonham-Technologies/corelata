import { useId, useState } from "react";
import { useResolvedPack } from "../../api/packs";
import { useEditSource } from "../../api/projects";
import { useInfo } from "../../api/system";
import type { SourceStatement, SourceView } from "../../api/types";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";

type Field = keyof SourceStatement;

/** The fields of a source's reference the analyst may state (CRL-138), as the form labels them. */
export const STATED_FIELDS: { field: Field; label: string; long?: boolean }[] = [
  { field: "descriptor", label: "Descriptor" },
  { field: "reliability_note", label: "Reliability note", long: true },
  { field: "date_of_information", label: "Date of information" },
  { field: "origin", label: "Origin" },
  { field: "access", label: "Access" },
];

function filled(stated: SourceStatement | undefined): Required<SourceStatement> {
  return {
    descriptor: stated?.descriptor ?? "",
    reliability_note: stated?.reliability_note ?? "",
    date_of_information: stated?.date_of_information ?? "",
    origin: stated?.origin ?? "",
    access: stated?.access ?? "",
  };
}

/** What a source's row says the analyst stated: the fields' names, or nothing. */
export function statedText(source: SourceView): string {
  const named = STATED_FIELDS.filter(({ field }) => source.stated?.[field]).map((f) => f.label);
  return named.length ? `You stated: ${named.join(", ").toLowerCase()}` : "";
}

/** A source's Details button and the form behind it (CRL-138): what the analyst knows about the
 * source that the text may not say. A value given here goes into every report started after,
 * in place of what the model would infer; an empty one leaves the field to the model. */
export function SourceDetails({ projectId, source }: { projectId: string; source: SourceView }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState(() => filled(source.stated));
  const edit = useEditSource(projectId);
  const info = useInfo();
  const lexicon = useResolvedPack(open ? (info.data?.default_pack ?? null) : null, null).data
    ?.lexicon;
  const id = useId();
  const suggestions: Partial<Record<Field, string[]>> = {
    descriptor: lexicon?.source_descriptors,
    access: lexicon?.source_access,
  };

  function close() {
    edit.reset();
    setOpen(false);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await edit.mutateAsync({ sourceId: source.id, stated: values });
      setOpen(false);
    } catch {
      // the mutation's error is shown in the form
    }
  }

  return (
    <>
      <button
        type="button"
        aria-label={`Details of ${source.name}`}
        onClick={() => {
          setValues(filled(source.stated));
          setOpen(true);
        }}
      >
        Details
      </button>
      <Dialog open={open} label={`Details of ${source.name}`} onClose={close}>
        <form onSubmit={(event) => void save(event)}>
          <h2 dir="auto">{source.name}</h2>
          <p className="muted">
            What you know about this source. Reports started from now on use what you give here in
            place of what the model infers from the text; leave a field empty to let the model fill
            it.
          </p>
          {STATED_FIELDS.map(({ field, label, long }) => {
            const fieldId = `${id}-${field}`;
            const options = suggestions[field] ?? [];
            const props = {
              id: fieldId,
              value: values[field],
              dir: "auto" as const,
              onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
                setValues({ ...values, [field]: event.target.value }),
            };
            return (
              <div className="field" key={field}>
                <label htmlFor={fieldId}>{label}</label>
                {long ? (
                  <textarea rows={3} {...props} />
                ) : (
                  <input {...props} list={options.length ? `${fieldId}-terms` : undefined} />
                )}
                {options.length ? (
                  <datalist id={`${fieldId}-terms`}>
                    {options.map((term) => (
                      <option key={term} value={term} />
                    ))}
                  </datalist>
                ) : null}
              </div>
            );
          })}
          {edit.error ? <ErrorMessage error={edit.error} /> : null}
          <div className="row end">
            <button type="button" onClick={close} disabled={edit.isPending}>
              Cancel
            </button>
            <button type="submit" className="primary" disabled={edit.isPending}>
              {edit.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
