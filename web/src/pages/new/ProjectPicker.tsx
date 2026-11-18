import { useId, useState } from "react";
import { useCreateProject, useProjects } from "../../api/projects";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";

/** New report without a project (M18 spec §5.1): choose one, or create one. */
export function ProjectPicker({
  projectId,
  onChange,
}: {
  projectId: string | null;
  /** `created` is true for a project just made here, so the page can move focus to it. */
  onChange: (projectId: string, created?: boolean) => void;
}) {
  const projects = useProjects();
  const create = useCreateProject();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const selectId = useId();
  const nameId = useId();

  function cancel() {
    setCreating(false);
    create.reset();
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    create.mutate(name.trim(), {
      onSuccess: (project) => {
        setCreating(false);
        setName("");
        onChange(project.id, true);
      },
    });
  }

  return (
    <section aria-label="Project" className="card">
      <h2>Which project is it for?</h2>
      {projects.isPending ? (
        <Loading what="Loading projects" />
      ) : (
        <div className="field">
          <label htmlFor={selectId}>Project</label>
          <div className="row">
            <select
              id={selectId}
              value={projectId ?? ""}
              onChange={(event) => onChange(event.target.value)}
            >
              <option value="">Choose a project…</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id} dir="auto">
                  {p.name}
                </option>
              ))}
            </select>
            {creating ? null : (
              <button type="button" onClick={() => setCreating(true)}>
                New project
              </button>
            )}
          </div>
        </div>
      )}
      {projects.error ? <ErrorMessage error={projects.error} /> : null}
      {creating ? (
        <form aria-label="New project" className="row" onSubmit={submit}>
          <label htmlFor={nameId} className="muted">
            Project name
          </label>
          <input
            id={nameId}
            value={name}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
            dir="auto"
          />
          <button type="submit" className="primary" disabled={!name.trim() || create.isPending}>
            Create
          </button>
          <button type="button" onClick={cancel}>
            Cancel
          </button>
        </form>
      ) : null}
      {create.error ? <ErrorMessage error={create.error} /> : null}
    </section>
  );
}
