import { createContext, useContext, useEffect } from "react";

/** The frame's setter for the project of the page on screen (M18 spec §3.3, "the active row"):
 * the project page names its project, a run's page the run's. */
export const ActiveProjectContext = createContext<(projectId: string | null) => void>(() => {});

/** Marks `projectId`'s row in the sidebar while the calling page is on screen. */
export function useActiveProject(projectId: string | null): void {
  const setActive = useContext(ActiveProjectContext);
  useEffect(() => {
    setActive(projectId);
    return () => setActive(null);
  }, [projectId, setActive]);
}

/** The browser tab's title (M18 spec §3.4); null leaves it as it is (still loading). */
export function useDocumentTitle(title: string | null): void {
  useEffect(() => {
    if (title !== null) document.title = title;
  }, [title]);
}
