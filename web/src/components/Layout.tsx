import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { useInfo } from "../api/system";
import { clearAllDrafts } from "../lib/draft";
import { keyBelongsToControl } from "../lib/keys";
import { useTheme } from "../theme/theme";
import { ErrorMessage } from "./ErrorMessage";
import { ActiveProjectContext } from "./frame";
import { HelpDialog } from "./HelpDialog";
import { Sidebar } from "./Sidebar";

/** Adapted from Coglossa's Layout (M18 spec §3.1): the header, the project sidebar and the main
 * area. Who is signed in and the sign-out page come from GET /api/system/info (Corelata has no
 * /api/me).
 *
 * Divergence from Coglossa (a Corelata improvement): the narrow-screen sidebar overlay is
 * keyboard-operable. Opening it moves focus to "+ New report"; Esc closes it and returns focus to
 * the toggle, unless a dialog is open, which takes that Esc; a link click that closes it moves focus to <main> (tabIndex -1), not to <body>. */
export function Layout() {
  const info = useInfo();
  const { theme, setChoice } = useTheme();
  const [help, setHelp] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const dark = theme === "dark";
  const toggleRef = useRef<HTMLButtonElement>(null);
  const newReportRef = useRef<HTMLAnchorElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!navOpen) return;
    newReportRef.current?.focus();
    function onEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      // an open dialog (Help, a confirmation) owns this Esc: one Esc closes one thing
      if (document.querySelector("dialog[open]")) return;
      setNavOpen(false);
      toggleRef.current?.focus();
    }
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [navOpen]);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "?" && !keyBelongsToControl(event.target, event.key)) setHelp(true);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="shell">
      <header className="topbar">
        <div className="row">
          <button
            type="button"
            ref={toggleRef}
            className="quiet narrow-only"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(!navOpen)}
          >
            Your projects
          </button>
          <Link to="/new" className="brand">
            Corelata
          </Link>
        </div>
        <div className="topbar-actions">
          <button
            type="button"
            className="quiet"
            aria-label={dark ? "Switch to the light theme" : "Switch to the dark theme"}
            onClick={() => setChoice(dark ? "light" : "dark")}
          >
            <span aria-hidden="true">{dark ? "☀" : "☾"}</span>
          </button>
          <button type="button" className="quiet" onClick={() => setHelp(true)}>
            Help
          </button>
          <NavLink to="/settings">Settings</NavLink>
          {info.data?.user ? <span className="user">{info.data.user}</span> : null}
          {info.data?.logout_url ? (
            <form
              method="post"
              action={info.data.logout_url}
              className="signout"
              onSubmit={clearAllDrafts}
            >
              <button type="submit" className="link">
                Sign out
              </button>
            </form>
          ) : null}
        </div>
      </header>
      {info.isError ? <ErrorMessage error={info.error} /> : null}
      <div className="workspace">
        <Sidebar
          open={navOpen}
          activeProject={activeProject}
          newReportRef={newReportRef}
          onNavigate={() => {
            setNavOpen(false);
            mainRef.current?.focus();
          }}
        />
        <main className="main" ref={mainRef} tabIndex={-1}>
          <ActiveProjectContext.Provider value={setActiveProject}>
            <Outlet />
          </ActiveProjectContext.Provider>
        </main>
      </div>
      <HelpDialog open={help} onClose={() => setHelp(false)} />
    </div>
  );
}
