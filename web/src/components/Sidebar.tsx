import { type Ref, useState } from "react";
import { Link } from "react-router";
import { useProjects } from "../api/projects";
import { useInfo } from "../api/system";
import { groupByDate } from "../lib/dates";
import { projectStatus } from "../lib/status";
import { ErrorMessage } from "./ErrorMessage";
import { Loading } from "./Loading";
import { StatusText } from "./StatusText";

/** Coglossa's: search appears once there are more projects than this. */
export const SEARCH_FROM = 15;

/** Adapted from Coglossa's Sidebar (M18 spec §3.3): + New report, then the projects, newest
 * activity first, grouped by date, one status each. No row menu: Corelata cannot rename or
 * delete a project. */
export function Sidebar({
  open,
  activeProject,
  onNavigate,
  newReportRef,
}: {
  open: boolean;
  activeProject: string | null;
  onNavigate: () => void;
  /** The frame focuses this link when the narrow-screen overlay opens. */
  newReportRef?: Ref<HTMLAnchorElement>;
}) {
  const projects = useProjects();
  const info = useInfo();
  const [search, setSearch] = useState("");
  const all = [...(projects.data ?? [])].sort(
    (a, b) => Date.parse(b.last_activity_at) - Date.parse(a.last_activity_at),
  );
  const term = search.trim().toLocaleLowerCase();
  const shown = term ? all.filter((p) => p.name.toLocaleLowerCase().includes(term)) : all;
  return (
    <div className={open ? "sidebar open" : "sidebar"}>
      <nav aria-label="Your projects" className="sidebar-nav">
        <Link to="/new" className="button primary new" ref={newReportRef} onClick={onNavigate}>
          + New report
        </Link>
        {all.length > SEARCH_FROM ? (
          <input
            type="search"
            aria-label="Search your projects"
            placeholder="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        ) : null}
        {projects.isPending ? <Loading /> : null}
        {projects.isError ? <ErrorMessage error={projects.error} /> : null}
        {projects.data && all.length === 0 ? (
          <p className="muted">Your projects will appear here.</p>
        ) : null}
        {term && all.length > 0 && shown.length === 0 ? (
          <p role="status" className="muted">
            {`No project matches "${search.trim()}".`}
          </p>
        ) : null}
        {groupByDate(shown, (p) => p.last_activity_at).map((group) => (
          <section key={group.label} aria-label={group.label}>
            <h2 className="group">{group.label}</h2>
            <ul>
              {group.items.map((p) => (
                <li key={p.id} className="project-row">
                  <Link
                    to={`/new?project=${p.id}`}
                    className="project-link"
                    aria-current={p.id === activeProject ? "page" : undefined}
                    aria-labelledby={`project-name-${p.id} project-status-${p.id}`}
                    onClick={onNavigate}
                  >
                    <span id={`project-name-${p.id}`} className="project-name" dir="auto">
                      {p.name}
                    </span>
                    <StatusText id={`project-status-${p.id}`} status={projectStatus(p)} />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>
      {info.data ? (
        <footer className="sidebar-foot muted" aria-label="Version">
          Corelata {info.data.version}
        </footer>
      ) : null}
    </div>
  );
}
