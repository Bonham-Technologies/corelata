# M18 Corelata on Coglossa's Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-41: Corelata's web app moves onto Coglossa's design system (tokens, base and frame styles, the theme mechanism with dark mode on every screen and inside the report frame, Noto Sans, the header and a project sidebar, the `Dialog`, `Menu` and `StatusText` components), speaks the reader's words instead of the engine's, reworks New report, the project page, Writing the report, Review and adds Settings and Help, with the three backend additions the sidebar and the header need (`ProjectView`'s summary, `RunSummary.review_decision`, `auth.logout_url`), while every behaviour M9 to M17 pinned stays as it is.

**Architecture:** The design layer is Coglossa's files copied with logged divergences: `tokens.css` (the only stylesheet with raw colours, enforced by a test), `base.css`, `shell.css`, `public/theme-init.js` (sets `data-theme` before the first paint) and `theme/theme.ts`; Corelata's own rules live in `new.css`, `run.css` and `review.css`, and `app.css` goes. The frame (`Layout`, `Sidebar`, `HelpDialog`) reads `GET /api/system/info` and `GET /api/projects`; the sidebar's statuses come from `lib/status.ts` (`runStatus`, `projectStatus`, `reportStatus`) and every engine word on screen from `lib/words.ts`, which a test checks against `schema/openapi.json`'s enums. The backend adds a project summary computed by three grouped statements in `store/runs.project_summaries`, two fields on `RunSummary` and one on `SystemInfo`. The report frame keeps `report.css`, its hash and the nonce: the bridge's nonce-bound style gains two theme classes, the frame is built in the page's theme and told when it changes.

**Tech Stack:** React 19, React Router 8, TanStack Query 5, openapi-fetch 0.17, Vite 8, Vitest 4, msw 2.15, Playwright 1.64, `@fontsource/noto-sans` 5.3.0; Python 3.12, SQLAlchemy 2.1 async + psycopg 3.3, FastAPI, pydantic 2; Postgres 16; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md`, sections 0 to 9 (Part A). Part B (§10–§22, the hosted demo) is M19 and not in this plan. The v1 spec `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` stays the authority for everything M18 does not change. Coglossa reference: `$COGLOSSA` is the read-only clone at `<scratchpad>/coglossa-ref` (Bonham-Technologies/coglossa at 72dd055; if it is gone, `gh repo clone Bonham-Technologies/coglossa "$COGLOSSA" && git -C "$COGLOSSA" checkout 72dd055`). Its UI spec is `$COGLOSSA/docs/superpowers/specs/2026-10-16-coglossa-ui-ux-design.md`. Screenshots of today's UI: the session scratchpad's `m18-shots/`.

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements (96.23% branches at the baseline; every new branch gets its test); `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean; `pnpm build` clean. `ci-status` is the required check. `make deploy-check` clean.
- Baselines on main at 3154118, re-measured for this plan: engine 956 passed (98.46%), api 171 (99.69%), web 211 Vitest in 32 files (98.45 / 96.23 / 99.59 / 99.5%), e2e 6. After every task in the scratch copy: web 308, 322, 322, 345, 354, 357, 372, 385 Vitest (Tasks 1 to 8); engine 964 and api 173 after Task 3; e2e 9 after Task 9.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). A single web file: `cd web && pnpm exec vitest run src/x.test.tsx`. Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`, `make e2e`, `make deploy-check`. Do not run the full pytest and Vitest suites concurrently. Never stop the dev Postgres container (`corelata-dev-postgres-1`); drop any database you create.
- Web tests mock every request with msw; `web/src/test/setup.ts` fails a test that makes an unmocked request. Poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`.
- **No runtime package but `@fontsource/noto-sans` 5.3.0** (R-M18-1), exact, the version and integrity Coglossa's lock has. No new dev package, and no Python dependency changes (R-M18-17).
- **No raw colour outside `web/src/styles/tokens.css`**: `no-raw-colours.test.ts` (copied) scans every sheet in `src/styles/`; the one colour pair outside it, the frame's claim highlight, is checked by `contrast.test.ts`. Every foreground/background pair a sheet uses is a row of `contrast.test.ts` (4.5:1 text, 3:1 meaningful borders, both themes).
- **rem sizes, `:focus-visible` in `--accent`, desktop first:** designed for 1280 px and wider with no maximum width; below 1100 px the review tabs stack under the frame; below 900 px the sidebar is an overlay opened from the header ("Your projects"). Nothing else is tuned for narrow screens. Status is always a word or a symbol plus a colour.
- **One schema change, no migration, one config field.** Task 3: `ProjectView` gains `last_activity_at`, `reports_writing`, `reports_to_review`, `latest_run` (`LatestRun`); `RunSummary` gains `review_decision` and `review_child_state`; `SystemInfo` gains `logout_url`; `make schema` changes `schema/openapi.json`, `schema/run-summary.schema.json` and `web/src/api/schema.d.ts`, committed with Task 3; a second `make schema` changes nothing. Config field `auth.logout_url` (operational, outside `config_hash`). No new API route, so `api/tests/test_openapi.py` is untouched (R-M18-22).
- **The air-gap bundle is unchanged in shape:** the image's web stage (`deploy/docker/app.Dockerfile`, `pnpm install --frozen-lockfile && pnpm build`) picks up the new `web/dist` (the Noto Sans files under `assets/` and `theme-init.js` at the root); `deploy/tests/check-bundle.sh` checks nothing inside `web/dist` and passes unchanged; the web SBOM lists the font package. The compose stack, `install.sh`, `backup.sh`, `restore.sh`, the air-gap CI job and the release workflow are not touched. The operator guide's sample Content-Security-Policy is not touched (`api/tests/test_csp_proxy.py` pins it word for word): it allows `/theme-init.js` (a file) and the fonts (`default-src 'self'`).
- **Behaviour that does not change** (spec §2.6): `POLL_MS` 3 s for a run without a live stream or with a pending rerun, the SSE fallback, discovery polling 1, 2, 4 s then 5 s and its ceiling `max(10 minutes, deadline_at − created_at + 15 s)`, `DISCOVERY_STALLED` word for word; `/new?project=&sources=&discovery=` with replace navigation, missing and foreign source ids, another project dropping both; `/runs/<id>/review?tab=&claim=` with the tab ids `provenance`, `audit`, `process`, `sources`; the `ReviewActions` button rules, M16's "accept is final", refetch on focus; the frame's `sandbox="allow-scripts"`, `srcdoc`, `FRAME_CSP` with the report stylesheet's hash and the nonce, inert links, the 200-character claim cap, `scroll` only for selections from outside; the routes `/`, `/new`, `/runs/:runId`, `/runs/:runId/review`, plus `/settings`. Tests that pin these keep their assertions; only selectors and visible words change.
- **`make e2e` between tasks:** the Playwright journeys use the screens' words, which Tasks 4 to 8 change; Task 9 rewrites them. Each of Tasks 1 to 8 gates on Vitest, lint and build (and pytest for Task 3), not on `make e2e` (R-M18-23). The branch is green on all of it before the PR.
- Commit messages end with exactly these two lines, nothing after them (R-M18-4):
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  (implementer subagents use their own harness's model line instead). Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .`. Plain single shell commands with `git -C <path>`.
- Version stays `0.1.6` (R-M18-5); the controller cuts 0.1.7 after the live rehearsal.
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8, R-M12-1 to R-M12-10, R-M13-1 to R-M13-12, R-M14-1 to R-M14-15, R-M15-1 to R-M15-22, R-M16-1 to R-M16-24 and R-M17-1 to R-M17-28 stay in force.
  - **R-M18-1 (font).** Add Noto Sans: `@fontsource/noto-sans` 5.3.0, the package and version Coglossa ships, so it is already vetted; 400 and 700 imported in `src/fonts.ts`. It is the only new runtime package.
  - **R-M18-2 (the report's theme).** The report frame follows the app's theme. The page tells the frame which theme to use. `report.css`, its hash in `FRAME_CSP` and the nonce mechanism stay. The report stylesheet needs no dark set: it already says `color-scheme: light dark` and uses no fixed colours, so `report.css` and its hash do not change (checked: `frameBridge.test.ts`'s hash test is untouched).
  - **R-M18-3 (sidebar).** The sidebar lists projects, with the summary fields of spec §7.1, computed by grouped queries with no N+1.
  - **R-M18-4 (attribution).** Implementers use their own harness's model line; the controller's commits end with the two lines above.
  - **R-M18-5 (version).** Version stays 0.1.6. The controller cuts 0.1.7 after the rehearsal.
  - Rulings this plan adds, from reading the code at 3154118 and applying Tasks 1 to 9 to a scratch copy of the repository (results under "Final verification"):
  - **R-M18-6 (the sidebar's last row of §3.3).** "Anything else" shows the latest report's own status from §4.2 (`runStatus`), not §4.3's step word: the only states that reach that row are an accepted report (already its own row) and a returned one whose revision is being or was written, which §4.3 would call "Ready to review". It reads "↺ returned".
  - **R-M18-7 (`RunSummary.review_child_state`).** §7.2's `review_decision` alone cannot tell a return whose revision ended without a report (to review again, M15) from one whose revision is live, so the Reports list would show "↺ returned" where the sidebar counts "to review". `RunSummary` also carries the stored `ReviewState.child_state` as `review_child_state`; `runStatus` reads `{state, decision, childState}` from a run's progress (`fromProgress`) and from a list row (`fromSummary`) alike. `LatestRun` keeps §7.1's four fields: a freed return is counted by `reports_to_review`, which comes first.
  - **R-M18-8 (Settings ▸ Status).** The doctor names a model server's failure `backend <name>` (and `model <key>`, `model <key> auditor schema`, `backends`); all four read "Corelata can't reach a model server (<check name>)…". `pack`, `pack names`, `prompts` and `coglossa` take the "any other" row. The full check is `probe=true`; the page's own read is `probe=false`.
  - **R-M18-9 (lint).** Corelata's eslint keeps `react-hooks/refs` on (Coglossa turns it off app-wide). Coglossa's `Menu` passes `close` (which focuses a ref) to its children during render: one `eslint-disable-next-line react-hooks/refs` with the reason, in `Menu.tsx` only. A divergence entry.
  - **R-M18-10 (frame theme mechanics).** The frame is built in the theme the page had when `ReportFrame` mounted (`withBridge(html, nonce, theme)` hands it to the bridge, whose sixth argument sets the class while the document is parsed), so a report never shows the computer's theme first. `ReportFrame` posts `{type: "corelata:theme", theme}` when the app's theme changes, and when a reloaded frame reports ready in a theme other than the app's; not at every ready. So the M14 tests' message counts hold unchanged and there is no flash. The theme rules ride in the bridge's nonce-bound style (`HIGHLIGHT_CSS` keeps its name, the frame tests compare against it). Unchanged: `FRAME_CSP`, the nonce, the highlight colours, every other message.
  - **R-M18-11 (an upload refused for its size).** A 413 that carries the API's own line ("big.txt is larger than the 1 MB upload limit (api.max_upload_mb)") shows that line on the file's chip, because it names the limit; a 413 without one (a proxy's limit) shows "too large for this server".
  - **R-M18-12 (the review banner).** A decision decides the banner (accepted; returned, revision live, written or ended without a report); without one, a delivery without a full check comes first, then the standards not met, then a clean report. The clean sentence reads "Ready to review. Every standard that could be checked was met.": §5.4's "the pack can check" would put the pack word in the main flow, which §4.1 keeps to the Sources tab and Settings. A freed return reads "Returned with a note. <how the revision ended>".
  - **R-M18-13 (words beyond the spec's tables).** The M15 rerun-outcome sentences in the reader's words: "The revised report couldn't be written: <error>. Return the report again or accept it." / "The revised report was stopped; …" / "The revised report stopped at the value check (not supported by the sources); …". The suggestions' live region is named "Suggestions" (was "Discovery"), its failure without text "No suggestions could be made.". "Waiting for Corelata to start looking…" (§4.3). Details: "ran N times", "Started N times: an earlier try stopped and the report started over.", "Nothing has started yet.". A failed run without an error: "No reason was recorded.". A stop that came too late: "A stop was asked for, but the report had already finished its last step, so it was delivered.". The team profile select's empty option: "Default (<profile>)" or "No team profile". The Standards tab: "No standards results were recorded.", "Every standard that could be checked was met.", "The standards check didn't finish: <reason>". The Sources tab: "Standards pack <name> (<hash 12>), team profile <name>" and "summarised before drafting". The not-found page: "Start a new report". "Cited in" joins its places with "; " (they hold commas) and words `alternatives[i]` as "Alternatives, item i+1".
  - **R-M18-14 (no engine word, checked).** `web/src/test/engine-words.ts` holds the words that must not reach the main flow (run, rerun, discovery, gate, audit, conveyor, conveying, conveyed, ingesting, iteration, verdict, evidence unit, finding, digested, pack) and `expectNoEngineWords(root)`, which reads the text and every `aria-label`. Page tests run it on the project page (sources, suggestions, reports), the writing page (live and an outcome), and Review (header, banner, Claims, Standards). "Coglossa run <id>" and a Coglossa locator (`coglossa:<run id>/…`) are allowed (Coglossa's words; locators are shown as they are, §4.1). The Process and Sources tabs, Settings ▸ Technical details and the writing page's Details fold keep the expert words (§4.4).
  - **R-M18-15 (uploads).** The chips live in the project page (`AddSources`), not in a module queue as in Coglossa: the page stays open while they upload. Files come by drop or by the (visually hidden) file input; a file of another type or over `max_upload_mb` is marked on its chip at once and never sent; Upload sends the rest one after another with the chosen "Add as" kind; an uploaded file's chip goes and its source appears (selected as today, R-M17-21); a failed one keeps its chip with the reason and Try again.
  - **R-M18-16 (the test harness).** Every page now renders the sidebar and a completed run's page reads its report for the tab title, so `web/src/test/server.ts` answers `GET /api/projects` with `[]` and any `GET /api/runs/:id/exports/report.json` with `reportJson` unless a test serves its own. `src/test/jsdom-env.ts` points `localStorage` at jsdom's (copied from Coglossa: Node 25 and later define their own, empty one); `setup.ts` guards its dialog shim for a test in the node environment (`fonts.test.ts`).
  - **R-M18-17 (the summary's statements).** Three statements for the whole list, whatever its length: (1) the projects, outer-joined to their newest source's `created_at` (a grouped subquery); (2) one aggregate over `run` grouped by `project_id` with `FILTER` clauses for writing (not terminal) and to review (completed, and `review_state->>'decision'` null, or `returned` with `child_state` failed, cancelled or gate_rejected), plus `max(created_at)` and `max(finished_at)`; (3) `DISTINCT ON (project_id) … ORDER BY project_id, created_at DESC, id DESC`, which `ix_run_project_created` serves. `get_project` runs the same three with a `WHERE`. The third is written out as SQL (`store.runs._LATEST_RUN`, a `text()` like the module's procrastinate statements): SQLAlchemy 2.1 (the lock's 2.1.4) deprecates `.distinct(column)`, a warning and so an error under `filterwarnings`, and its replacement `postgresql.distinct_on` does not exist in 2.0, which the engine's floor `>=2.0.36` still allows; raising the floor would also move both locks' format revision (3 to 5 under uv 0.13), churn this milestone does not need. `store.runs.FREED_BY` is `service.FREED_BY`'s set, pinned by a test.
  - **R-M18-18 (tab titles §3.4 leaves open).** A report that ended without one: "<its status> – <project name>" ("Not supported by the sources – Black Sea"). The not-found and error pages leave the title as it was.
  - **R-M18-19 (the active row).** Pages name their project to the frame through a context (`useActiveProject`): the project page its `?project`, a run's pages the run's `project_id`. The sidebar does not read the run itself: a second observer of the run's query would poll it beside a live stream.
  - **R-M18-20 (the writing page reads the report).** Once a run is completed its page reads `report.json` (cached for Review, `staleTime: Infinity`) for the tab's title and for "N standards not met" in the outcome.
  - **R-M18-21 (files).** Pages keep their file and component names (`NewRunPage`, `RunList`, `RunOptions`, `StageTimeline.tsx`, `CancelRun`, `AuditTab`, `ProvenanceTab`) so the history stays readable; `UploadSource.tsx` is replaced by `AddSources.tsx`; `StateBadge.tsx` and `format.ts`'s `STATE_LABELS` go (their words moved to `lib/words.ts` and `lib/status.ts`).
  - **R-M18-22 (route list).** `test_every_screen_has_its_routes` already lists `/api/system/info`, `/api/system/doctor` and `/api/packs`; §7.4's "gains the Settings screen" needs no edit.
  - **R-M18-23 (e2e between tasks).** As in the constraint above.
  - **R-M18-24 (the steps).** Eight rows (§4.3): Waiting to start, the six stages, Ready to review. Waiting to start is "now" while the run is `created`, "done" once a stage has run, "not yet" for a run that ended before it started; Ready to review is "done" when completed. A stage is "now" when it is the run's state (and the page marks it `aria-current="step"` only while the run is live), "done" or "failed" by its last attempt, otherwise "not yet". The current step of a revision (drafting, editing, checking with `iteration > 0`) reads "now · revision N of M". The symbol is `aria-hidden`; the word is the text.
  - **R-M18-25 (Standards groups).** Not met: rules that are not advisory whose latest verdict is `fail`. Met and not applicable: the other rules that are not advisory. Advisory: rules whose pack `checkability` is `advisory`. Without the pack (titles unavailable) nothing says which rules are advisory, so they group by verdict alone. A rule's history shows only when it has more than one verdict.
  - **R-M18-26 (the status pill).** `reportStatus`: clean "✓ Meets the standards" (ok); open rules "✗ N standards not met" (warn); `findings_open` with none open, so only a degradation, "⚠ Checked in part" (warn).

## Review Focus

1. **A light flash on load, in the app or in the report frame.** A stored dark theme must be on `<html>` before `<body>` is parsed, and the report frame must open in the app's theme even when the computer's differs. Pinned in Task 1 (`theme-init.test.ts`, every stored value and the computer's setting), Task 7 (`frameTheme.test.tsx`: "opens the frame in the app's theme and tells it when the theme changes") and Task 9 (`theme.spec.ts`: `themeAtBody` is "dark" on four screens; "a light app on a dark computer shows the report light").
2. **The report frame's theme against its CSP.** The theme classes must apply under the frame's own policy and under the operator guide's sample policy, without `report.css` or its hash changing. Pinned in Task 7 (`frameTheme.test.tsx`: the rules are inside the nonce-bound `HIGHLIGHT_CSS`; `frameBridge.test.ts`'s policy and hash tests unchanged) and Task 9 (`csp.spec.ts` in both themes: no violation, the frame's root has the class).
3. **A word map that misses an engine word on screen.** A state, verdict, severity or claim kind the API adds later, or a reworded component that leaks "run", "audit" or "gate". Pinned in Task 4 (`words.test.ts`: every `RunState`, `Verdict`, `Severity` and `ClaimKind` in `schema/openapi.json` has a word) and Tasks 5, 6, 7 (`expectNoEngineWords` on the project page, the writing page and Review).
4. **A sidebar summary query that grows with the project count.** Pinned in Task 3 (`test_the_summaries_take_three_statements_however_many_projects`: three statements for 1 and for 20 projects, counted with `before_cursor_execute`) and its correctness across mixed states (`test_the_summary_counts_writing_and_to_review_and_finds_the_newest_run`, including a return whose revision failed, was stopped or not supported).
5. **A reload of `/new?project&discovery&sources` in the new frame, and switching projects from the sidebar.** The sidebar's links name the project alone, so they must drop the discovery and the sources, and an in-flight discovery for the old project must not write itself into the new one's URL. Pinned in Task 5 (`NewRunPage.test.tsx`: "keeps the chosen sources in the URL, so a reload selects them again", "choosing another project drops the discovery and the chosen sources", "a discovery that starts for the old project does not write itself into the new project's URL", both now switching through the sidebar) and Task 9 (`journey.spec.ts` reloads with the discovery in the URL).

---

## File structure

| Path | Responsibility |
|---|---|
| `web/src/styles/tokens.css`, `base.css`, `shell.css` (copied) | design values; element defaults, buttons, tones, dialog, menu, `.card`, Settings rules; the frame (Task 1, Task 8 adds the Settings rules) |
| `web/src/styles/new.css`, `run.css`, `review.css` | Corelata's screens on the tokens (Task 1 ports today's rules; Tasks 5, 6, 7 replace them) |
| `web/src/styles/contrast.test.ts`, `no-raw-colours.test.ts`, `tokens.test.ts` (copied) | the colour pairs and the frame's highlight pair; no raw colours; backdrop and base sizes (Task 1) |
| `web/public/theme-init.js`, `web/src/theme/theme.ts` (+ tests, copied), `web/index.html`, `web/src/main.tsx` | the theme before the first paint and its store (Task 1) |
| `web/src/fonts.ts`, `fonts.test.ts`, `web/package.json`, `web/pnpm-lock.yaml` | Noto Sans (Task 1) |
| `web/src/test/jsdom-env.ts`, `jsdom-storage.ts` (+ test), `setup.ts`, `server.ts`, `poll.ts`, `fixtures.ts`, `engine-words.ts` | the harness (Tasks 1, 3, 4, 5, 6, 7, 8) |
| `web/src/components/Dialog.tsx`, `Menu.tsx`, `StatusText.tsx` (+ tests), `web/src/lib/dates.ts`, `keys.ts` (+ tests), `lib/status.ts` | Coglossa's components and helpers (Task 2) |
| `engine/corelata/schema/progress.py`, `store/runs.py`, `service.py`, `config.py`, `api/corelata_api/routes/projects.py`, `system.py`, `schema/*`, `web/src/api/schema.d.ts` | the summary, the run list's decision, `logout_url` (Task 3) |
| `web/src/components/Layout.tsx`, `Sidebar.tsx`, `HelpDialog.tsx`, `frame.ts`, `web/src/lib/words.ts`, `lib/status.ts`, `web/src/api/projects.ts`, `runs.ts`, `events.ts` | the frame, the word map, the statuses, the sidebar's freshness (Task 4) |
| `web/src/pages/new/*` | New report and the project page (Task 5) |
| `web/src/pages/run/*` | Writing the report (Task 6) |
| `web/src/pages/review/*` | Review, the frame's theme (Task 7) |
| `web/src/settings/*`, `web/src/api/system.ts`, `web/src/routes.tsx` | Settings (Task 8) |
| `web/e2e/*` | the journeys, dark mode, the sample policy in both themes (Task 9) |
| `README.md`, the v1 spec, the M18 spec, `docs/operator-guide.md`, `docs/m18-followups.md` | docs (Task 10) |

Order: 1, 2, 3, then 4 (it needs Task 2's components and Task 3's fields), then 5, 6, 7, 8 in any order after 4 (each owns its pages; Task 7 edits `lib/status.ts` and `lib/words.ts` after Task 4, and `NewRunPage.test.tsx` and `engine-words.ts` after Task 5), then 9 and 10.

How to read the code blocks: a whole file is given in full; a change to a file that exists is a patch (`git apply` it from the repository root, or make the same edit by hand); a file copied from Coglossa is "copy `$COGLOSSA/<path>`, then this patch on it" (`cp "$COGLOSSA/<path>" <path>`; the patch's `coglossa/` and `corelata/` prefixes name the two files: apply it with `patch -p1 <path> < the-patch` after the copy, or edit by hand). Every block was produced from the scratch copy the plan was checked on.

---

### Task 1: Tokens, base styles, the theme before the first paint, Noto Sans, the contrast test

**Files:**
- Copy from Coglossa (with the patches below): `web/src/styles/tokens.css`, `web/src/styles/base.css`, `web/src/styles/shell.css`, `web/src/styles/contrast.test.ts`, `web/src/styles/no-raw-colours.test.ts`, `web/src/styles/tokens.test.ts`, `web/public/theme-init.js`, `web/src/theme/theme.ts`, `web/src/theme/theme.test.ts`, `web/src/theme/theme-init.test.ts`, `web/src/test/jsdom-storage.ts`, `web/src/test/jsdom-storage.test.ts`
- Create: `web/src/styles/new.css`, `web/src/styles/run.css`, `web/src/styles/review.css`, `web/src/fonts.ts`, `web/src/fonts.test.ts`
- Delete: `web/src/styles/app.css`
- Modify: `web/package.json`, `web/pnpm-lock.yaml`, `web/index.html`, `web/src/main.tsx`, `web/eslint.config.js`, `web/src/test/jsdom-env.ts`, `web/src/test/setup.ts`, `web/src/components/Layout.tsx`, `web/src/components/Layout.test.tsx`, `web/src/pages/run/StageTimeline.tsx`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the token names (`--bg`, `--surface`, `--surface-2`, `--border`, `--border-strong`, `--text`, `--text-muted`, `--accent`, `--accent-text`, `--ok`, `--warn`, `--warn-tint`, `--warn-tint-strong`, `--danger`, `--selected`, `--shadow`, `--space-1…6`, `--radius-1/2`, `--text-xs…xl`, `--topbar-height`, `--sidebar-width`, `--dialog-width`, `--menu-min-width`, `--border-width`, `--review-side-width`, `--frame-min-height`); base classes `primary`, `quiet`, `danger`, `link` buttons, `.button`, `.muted`, `.error`, `.notice`, `.badge`, `.card`, `.row` (`.end`, `.between`), `.field`, `.visually-hidden`, `.tone-ok|warn|busy|bad|none`, `dialog.dialog`, `.menu`, `.menu-list`; shell classes `.shell`, `.topbar`, `.brand`, `.topbar-actions`, `.workspace`, `.sidebar` (`.open`), `.sidebar .new`, `.group`, `.project-row`, `.project-link`, `.project-name`, `.sidebar-foot`, `.status`, `.main`, `.shortcuts`, `.narrow-only`; `theme.ts`: `ThemeChoice`, `Theme`, `THEME_KEY = "corelata.theme"`, `storedChoice()`, `resolveTheme()`, `applyTheme()`, `setThemeChoice()`, `useTheme(): {choice, theme, setChoice}`, `resetThemeForTests()`; `fonts.ts`: `FONT_FAMILIES`.

- [ ] **Step 1: Copy the tests and write the new ones**

Copy `$COGLOSSA/web/src/styles/no-raw-colours.test.ts`, `$COGLOSSA/web/src/styles/tokens.test.ts`, `$COGLOSSA/web/src/theme/theme.test.ts`, `$COGLOSSA/web/src/theme/theme-init.test.ts` and `$COGLOSSA/web/src/test/jsdom-storage.test.ts` to the same paths under `web/`; each is used as it is, as the lines below confirm:

`web/src/styles/no-raw-colours.test.ts`: _(identical to Coglossa's: copy it as it is)_

`web/src/styles/tokens.test.ts`: _(identical to Coglossa's: copy it as it is)_

`web/src/theme/theme.test.ts`: _(identical to Coglossa's: copy it as it is)_

`web/src/theme/theme-init.test.ts`: _(identical to Coglossa's: copy it as it is)_

`web/src/test/jsdom-storage.test.ts`: _(identical to Coglossa's: copy it as it is)_

`theme.test.ts` imports `THEME_KEY` rather than naming the key, so it checks `corelata.theme` once `theme.ts` says so.

Copy `$COGLOSSA/web/src/styles/contrast.test.ts`, then add the frame's highlight pair (spec §2.2):



```diff
--- coglossa/web/src/styles/contrast.test.ts
+++ corelata/web/src/styles/contrast.test.ts
@@ -1,5 +1,7 @@
 import { readFileSync } from "node:fs";
+import { HIGHLIGHT_CSS } from "../pages/review/frameBridge";
 
+// Copied from Coglossa (spec §2.2); the frame's highlight pair at the end is Corelata's.
 // Read from disk: Vitest serves stylesheets imported with ?raw as empty strings
 // (tests run from web/).
 const tokens = readFileSync("src/styles/tokens.css", "utf8");
@@ -78,3 +80,13 @@
     expect(contrast(colours[fg]!, colours[bg]!)).toBeGreaterThanOrEqual(min);
   });
 });
+
+// The report frame's claim highlight is the one colour pair outside tokens.css: the bridge sets
+// it inside the sandboxed frame, where the app's tokens do not reach (spec §2.2, frameBridge.ts).
+it("gives the frame's claim highlight 4.5:1, in either theme", () => {
+  const rule = /\.corelata-highlight \{([^}]*)\}/.exec(HIGHLIGHT_CSS)?.[1] ?? "";
+  const background = /background: (#[0-9a-fA-F]{6})/.exec(rule)?.[1];
+  const colour = /(?:^|[\s;])color: (#[0-9a-fA-F]{6})/.exec(rule)?.[1];
+  expect([colour, background]).toEqual(["#1a1a1a", "#fff3b0"]);
+  expect(contrast(colour!, background!)).toBeGreaterThanOrEqual(4.5);
+});
```


Create `web/src/fonts.test.ts` (adapted from Coglossa's: one family):

```ts
// @vitest-environment node
import { readFileSync } from "node:fs";
import { FONT_FAMILIES } from "./fonts";

// Adapted from Coglossa's fonts.test.ts (spec §2.4): one family, Noto Sans.
const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as {
  dependencies: Record<string, string>;
};
const fontsSource = readFileSync(new URL("./fonts.ts", import.meta.url), "utf8");
const css = readFileSync(new URL("./styles/base.css", import.meta.url), "utf8");
const fontPackages = Object.keys(pkg.dependencies).filter((d) => d.startsWith("@fontsource/"));

it("depends on Noto Sans at the version Coglossa ships, and on no other font", () => {
  expect(pkg.dependencies["@fontsource/noto-sans"]).toBe("5.3.0");
  expect(fontPackages).toEqual(["@fontsource/noto-sans"]);
});

it("imports the regular and bold faces of every font package it depends on", () => {
  const imported = [...fontsSource.matchAll(/import "(@fontsource\/[^/]+)\/(\d+)\.css"/g)];
  expect(imported.map((m) => `${m[1]}/${m[2]}`)).toEqual([
    "@fontsource/noto-sans/400",
    "@fontsource/noto-sans/700",
  ]);
});

it("starts the page's font stack with Noto Sans and falls back to the computer's fonts", () => {
  const stack = /--font-stack:([^;]+);/.exec(css)?.[1] ?? "";
  const names = [...stack.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  expect(names[0]).toBe(FONT_FAMILIES[0]);
  expect(stack).toContain("system-ui");
  expect(stack.trim().endsWith("sans-serif")).toBe(true);
});
```

Add to `web/src/components/Layout.test.tsx` (the toggle lands on today's top bar now; Task 4 moves it):

```diff
diff --git a/web/src/components/Layout.test.tsx b/web/src/components/Layout.test.tsx
index 9723c7c..5859f06 100644
--- a/web/src/components/Layout.test.tsx
+++ b/web/src/components/Layout.test.tsx
@@ -59,3 +59,19 @@ it("replaces a crashing page inside the layout", async () => {
   expect(await screen.findByRole("alert")).toBeInTheDocument();
   expect(screen.getByRole("link", { name: "Corelata" })).toBeInTheDocument();
 });
+
+it("switches the theme from the header and names the theme it switches to", async () => {
+  localStorage.clear();
+  vi.stubGlobal("matchMedia", () => ({
+    matches: false,
+    addEventListener() {},
+    removeEventListener() {},
+  }));
+  const { user } = renderApp("/new");
+  await user.click(await screen.findByRole("button", { name: "Switch to the dark theme" }));
+  expect(document.documentElement.dataset.theme).toBe("dark");
+  expect(localStorage.getItem("corelata.theme")).toBe("dark");
+  await user.click(screen.getByRole("button", { name: "Switch to the light theme" }));
+  expect(document.documentElement.dataset.theme).toBe("light");
+  localStorage.clear();
+});
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd web && pnpm exec vitest run src/styles src/theme src/fonts.test.ts src/test/jsdom-storage.test.ts src/components/Layout.test.tsx`
Expected: FAIL: `ENOENT … src/styles/tokens.css`, `Cannot find module './theme'`, `Failed to resolve import "../../public/theme-init.js?raw"`, `Cannot find module './jsdom-storage'`, `Cannot find module './fonts'`, and the toggle test finds no "Switch to the dark theme" button.

- [ ] **Step 3: The font**

Run: `cd web && pnpm add @fontsource/noto-sans@5.3.0 --save-exact`
Expected: `package.json` gains `"@fontsource/noto-sans": "5.3.0"` first under `dependencies`, and `pnpm-lock.yaml` gains exactly:

```diff
diff --git a/web/pnpm-lock.yaml b/web/pnpm-lock.yaml
index 3c0dd57..a63c213 100644
--- a/web/pnpm-lock.yaml
+++ b/web/pnpm-lock.yaml
@@ -8,6 +8,9 @@ importers:
 
   .:
     dependencies:
+      '@fontsource/noto-sans':
+        specifier: 5.3.0
+        version: 5.3.0
       '@tanstack/react-query':
         specifier: 5.104.3
         version: 5.104.3(react@19.3.1)
@@ -435,6 +438,9 @@ packages:
       '@noble/hashes':
         optional: true
 
+  '@fontsource/noto-sans@5.3.0':
+    resolution: {integrity: sha512-fBCog2PY7DiVVTEEqtI/Qdinx/knobHYfoGpjFXdfBX5RoJaBp1Prw2G75p0OIsdlMZg3cLo0c+YbIUYOxnQJw==}
+
   '@humanfs/core@0.19.2':
     resolution: {integrity: sha512-UhXNm+CFMWcbChXywFwkmhqjs3PRCmcSa/hfBgLIb7oQ5HNb1wS0icWsGtSAUNgefHeI+eBrA8I1fxmbHsGdvA==}
     engines: {node: '>=18.18.0'}
@@ -2207,6 +2213,8 @@ snapshots:
 
   '@exodus/bytes@1.16.0': {}
 
+  '@fontsource/noto-sans@5.3.0': {}
+
   '@humanfs/core@0.19.2':
     dependencies:
       '@humanfs/types': 0.15.0
```

(the integrity is the one in `$COGLOSSA/web/pnpm-lock.yaml`; `grep -A1 "'@fontsource/noto-sans@5.3.0':" "$COGLOSSA/web/pnpm-lock.yaml"` shows it).

Create `web/src/fonts.ts`:

```ts
// Spec §2.4 (R-M18-1): Noto Sans 400 and 700, the package and version Coglossa ships, so the two
// products share a typeface and the customer has already vetted it. The app works offline, so the
// font ships with it; other scripts fall back to the computer's fonts.
import "@fontsource/noto-sans/400.css";
import "@fontsource/noto-sans/700.css";

/** The CSS family names, in the order of the font stack in styles/base.css. */
export const FONT_FAMILIES: readonly string[] = ["Noto Sans"];
```

- [ ] **Step 4: Copy the design files**

`cp "$COGLOSSA/web/src/styles/tokens.css" web/src/styles/tokens.css`, then:



```diff
--- coglossa/web/src/styles/tokens.css
+++ corelata/web/src/styles/tokens.css
@@ -1,7 +1,9 @@
-/* Spec §7.2: every colour, space, radius, text size and shadow the app uses. Other stylesheets
-   use these names only (no-raw-colours.test.ts); contrast.test.ts checks the colour pairs.
-   theme-init.js sets data-theme before the first paint; without it the light set applies.
-   dialog::backdrop gets the colours too: it does not inherit custom properties everywhere. */
+/* Copied from Coglossa's web/src/styles/tokens.css (docs/superpowers/specs/
+   2026-10-20-corelata-design-system-and-hosted-demo.md §2.2): every colour, space, radius, text
+   size and shadow the app uses. Other stylesheets use these names only (no-raw-colours.test.ts);
+   contrast.test.ts checks the colour pairs. theme-init.js sets data-theme before the first
+   paint; without it the light set applies. dialog::backdrop gets the colours too: it does not
+   inherit custom properties everywhere. Divergence: two layout tokens at the end. */
 :root,
 :root[data-theme="light"],
 dialog::backdrop {
@@ -66,4 +68,7 @@
   --dialog-width: 36rem;
   --menu-min-width: 14rem;
   --border-width: 1px;
+  /* Corelata's review screen (spec §5.4) */
+  --review-side-width: 30rem;
+  --frame-min-height: 30rem;
 }
```


`cp "$COGLOSSA/web/src/styles/base.css" web/src/styles/base.css`, then (one-family font stack; the Han `:lang()` rules, `mark`, `pre.config`, `.signals` and `.history` dropped; `.card` added):



```diff
--- coglossa/web/src/styles/base.css
+++ corelata/web/src/styles/base.css
@@ -1,4 +1,7 @@
-/* Element defaults and shared classes, on the design values only (spec §7). */
+/* Copied from Coglossa's web/src/styles/base.css (spec §2.2): element defaults and shared
+   classes, on the design values only. Divergences: a one-family font stack (§2.4); the Han
+   :lang() rules, mark, pre.config, .signals and .history are dropped (Coglossa-only screens);
+   .card is Corelata's. */
 *,
 *::before,
 *::after {
@@ -10,30 +13,7 @@
 }
 
 :root {
-  --font-stack:
-    "Noto Sans", "Noto Sans Arabic", "Noto Sans Hebrew", "Noto Sans Bengali", "Noto Sans Thai",
-    "Noto Sans Ethiopic", "Noto Sans SC", "Noto Sans JP", "Noto Sans KR", "Noto Sans TC",
-    "Noto Sans HK", "Noto Nastaliq Urdu", "Noto Sans Gujarati", "Noto Sans Gurmukhi",
-    "Noto Sans Kannada", "Noto Sans Malayalam", "Noto Sans Tamil", "Noto Sans Telugu",
-    "Noto Sans Oriya", "Noto Sans Sinhala", "Noto Serif Tibetan", "Noto Sans Khmer",
-    "Noto Sans Lao", "Noto Sans Myanmar", "Noto Sans Armenian", "Noto Sans Georgian",
-    "Noto Sans Vithkuqi", "Noto Sans Thaana", "Noto Sans Syriac", "Noto Sans Mongolian",
-    "Noto Serif Yezidi", "Noto Sans Tifinagh", "Noto Sans NKo", "Noto Sans Adlam", "Noto Sans Vai",
-    "Noto Sans Bamum", "Noto Sans Bassa Vah", "Noto Sans Mende Kikakui", "Noto Sans Cherokee",
-    "Noto Sans Canadian Aboriginal", "Noto Sans Osage", "Noto Sans Ol Chiki", "Noto Sans Javanese",
-    "Noto Sans Balinese", "Noto Sans Sundanese", "Noto Sans Buginese", "Noto Sans Chakma",
-    "Noto Sans Meetei Mayek", "Noto Sans Hanifi Rohingya", "Noto Sans Yi", "Noto Sans Lisu",
-    "Noto Sans Tai Viet", "Noto Sans New Tai Lue", "Noto Sans Tai Tham", "Noto Sans Kayah Li",
-    "Noto Sans Pahawh Hmong", "Noto Sans Miao", "Noto Serif NP Hmong", "Noto Sans Symbols",
-    "Noto Sans Symbols 2", "Noto Sans Math", "Noto Sans SignWriting", "Noto Sans Limbu",
-    "Noto Sans Lepcha", "Noto Sans Batak", "Noto Sans Rejang", "Noto Sans Tai Le",
-    "Noto Sans Saurashtra", "Noto Sans Cham", "Noto Sans Syloti Nagri", "Noto Sans Newa",
-    "Noto Sans Tagalog", "Noto Sans Hanunoo", "Noto Sans Buhid", "Noto Sans Tagbanwa",
-    "Noto Sans Samaritan", "Noto Sans Mandaic", "Noto Sans Coptic", "Noto Sans Sora Sompeng",
-    "Noto Sans Masaram Gondi", "Noto Sans Gunjala Gondi", "Noto Sans Nag Mundari",
-    "Noto Sans Wancho", "Noto Sans Mro", "Noto Sans Pau Cin Hau", "Noto Sans Medefaidrin",
-    "Noto Sans Warang Citi", "Noto Sans Tangsa", "Noto Sans Sunuwar", "Noto Sans Khudawadi",
-    "Noto Sans Tirhuta", "Noto Serif Dogra", "Noto Serif Ahom", "Noto Serif Toto", sans-serif;
+  --font-stack: "Noto Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
 }
 
 body {
@@ -270,23 +250,6 @@
   color: var(--accent);
 }
 
-/* A browser picks Han glyph forms by language: SC and JP come before TC and HK in the stack, so
-   a passage's own face goes first when it carries `lang`. */
-:lang(ja) {
-  font-family: "Noto Sans JP", var(--font-stack);
-}
-:lang(ko) {
-  font-family: "Noto Sans KR", var(--font-stack);
-}
-:lang(zh-Hant),
-:lang(zh-TW),
-:lang(zh-MO) {
-  font-family: "Noto Sans TC", var(--font-stack);
-}
-:lang(zh-HK) {
-  font-family: "Noto Sans HK", "Noto Sans TC", var(--font-stack);
-}
-
 table {
   border-collapse: collapse;
   width: 100%;
@@ -313,34 +276,20 @@
   margin: 0;
 }
 
-mark {
-  background: var(--warn-tint-strong);
-  color: var(--text);
-}
-
-pre.config {
-  background: var(--surface-2);
-  padding: var(--space-3);
-  overflow: auto;
-  max-height: 30rem;
-}
-
 .two-columns {
   display: grid;
   grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
   gap: var(--space-4);
 }
 
-.signals th {
-  font-weight: 400;
-  color: var(--text-muted);
-}
-
-.history del {
-  color: var(--danger);
-}
-
-.history ins {
-  color: var(--ok);
-  text-decoration: none;
-}
+.card {
+  background: var(--surface);
+  border: var(--border-width) solid var(--border);
+  border-radius: var(--radius-2);
+  padding: var(--space-4) var(--space-5);
+  margin-bottom: var(--space-4);
+}
+
+.card > h2 {
+  font-size: var(--text-md);
+}
```


`cp "$COGLOSSA/web/src/styles/shell.css" web/src/styles/shell.css`, then (project rows, no row menu, the sidebar's foot):



```diff
--- coglossa/web/src/styles/shell.css
+++ corelata/web/src/styles/shell.css
@@ -1,4 +1,5 @@
-/* Spec §3.1, §7.3: the frame. */
+/* Copied from Coglossa's web/src/styles/shell.css (spec §2.2, §3): the frame. Divergences:
+   project rows instead of set rows, no row menu, a sidebar footer with the version. */
 .shell {
   min-height: 100vh;
   display: flex;
@@ -72,23 +73,28 @@
   color: var(--text-muted);
 }
 
+.sidebar-foot {
+  margin-top: var(--space-5);
+  font-size: var(--text-sm);
+}
+
 .sidebar ul {
   list-style: none;
   margin: 0;
   padding: 0;
 }
 
-.set-row {
+.project-row {
   display: flex;
   align-items: center;
   border-radius: var(--radius-1);
 }
 
-.set-row:hover {
+.project-row:hover {
   background: var(--surface-2);
 }
 
-.set-link {
+.project-link {
   flex: 1;
   min-width: 0;
   display: flex;
@@ -99,11 +105,11 @@
   text-decoration: none;
 }
 
-.set-link.active {
+.project-link[aria-current="page"] {
   background: var(--selected);
 }
 
-.set-name {
+.project-name {
   overflow: hidden;
   text-overflow: ellipsis;
   white-space: nowrap;
@@ -111,11 +117,6 @@
 
 .status {
   font-size: var(--text-sm);
-}
-
-.row-menu > button {
-  border-color: transparent;
-  background: transparent;
 }
 
 .main {
```


`cp "$COGLOSSA/web/public/theme-init.js" web/public/theme-init.js`, then:



```diff
--- coglossa/web/public/theme-init.js
+++ corelata/web/public/theme-init.js
@@ -1,9 +1,10 @@
-// Spec §7.1: apply the saved theme before the page draws, so it never flashes light.
+// Copied from Coglossa (spec §2.2): apply the saved theme before the page draws, so it never
+// flashes light.
 // Keep in step with src/theme/theme.ts (THEME_KEY and the "system" rule).
 (function () {
   var choice = "system";
   try {
-    choice = localStorage.getItem("coglossa.theme") || "system";
+    choice = localStorage.getItem("corelata.theme") || "system";
   } catch {
     choice = "system";
   }
```


`cp "$COGLOSSA/web/src/theme/theme.ts" web/src/theme/theme.ts`, then:



```diff
--- coglossa/web/src/theme/theme.ts
+++ corelata/web/src/theme/theme.ts
@@ -1,10 +1,11 @@
 import { useSyncExternalStore } from "react";
 
-/** Spec §7.1: the reader's theme. "system" follows the computer's setting, live. */
+/** Copied from Coglossa (spec §2.2): the reader's theme. "system" follows the computer's
+ * setting, live. */
 export type ThemeChoice = "system" | "light" | "dark";
 export type Theme = "light" | "dark";
 
-export const THEME_KEY = "coglossa.theme";
+export const THEME_KEY = "corelata.theme";
 const DARK_QUERY = "(prefers-color-scheme: dark)";
 
 // When the browser refuses storage (a private window, a policy), the choice lasts the session.
```


`cp "$COGLOSSA/web/src/test/jsdom-storage.ts" web/src/test/jsdom-storage.ts` (_(identical to Coglossa's: copy it as it is)_), and point the environment at it (Corelata keeps its own `jsdom-env.ts`):

```diff
diff --git a/web/src/test/jsdom-env.ts b/web/src/test/jsdom-env.ts
index 0a1923e..c0b060b 100644
--- a/web/src/test/jsdom-env.ts
+++ b/web/src/test/jsdom-env.ts
@@ -1,6 +1,9 @@
 import { builtinEnvironments, type Environment } from "vitest/environments";
+import { pointStorageAtJsdom } from "./jsdom-storage";
 
-// jsdom's AbortController breaks react-router's Node `Request`; keep Node's.
+// jsdom's AbortController breaks react-router's Node `Request`; keep Node's. Node 25 and later
+// define their own (empty) localStorage, which hides jsdom's; the theme tests need jsdom's
+// (copied from Coglossa, spec §2.2).
 const env: Environment = {
   ...builtinEnvironments.jsdom,
   name: "jsdom-node-abort",
@@ -8,6 +11,7 @@ const env: Environment = {
     const NodeAbortController = global.AbortController;
     const result = await builtinEnvironments.jsdom.setup(global, options);
     global.AbortController = NodeAbortController;
+    pointStorageAtJsdom(global);
     return result;
   },
 };
```

Guard the dialog shim for the node environment `fonts.test.ts` runs in:

```diff
diff --git a/web/src/test/setup.ts b/web/src/test/setup.ts
index c9d4281..3d6880c 100644
--- a/web/src/test/setup.ts
+++ b/web/src/test/setup.ts
@@ -5,13 +5,16 @@ import { server } from "./server";
 
 configure({ asyncUtilTimeout: 5000 });
 
-// jsdom has no HTMLDialogElement.showModal/close: provide the minimum the components use.
-HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
-  this.open = true;
-};
-HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
-  this.open = false;
-};
+// jsdom has no HTMLDialogElement.showModal/close: provide the minimum the components use. A test
+// file in the node environment (fonts.test.ts) has no DOM at all.
+if (typeof HTMLDialogElement !== "undefined") {
+  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
+    this.open = true;
+  };
+  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
+    this.open = false;
+  };
+}
 
 // msw's "error" strategy only prints the request and fails that fetch; the component under test
 // shows a network error and the test still passes. Record every unhandled request and fail the
```

- [ ] **Step 5: Corelata's screen sheets, on the tokens**

`git rm web/src/styles/app.css`. Its rules move onto the tokens. The frame's rules are `shell.css`'s; between this task and Task 4 today's top bar (`.app`, `main`, `footer`) has only `shell.css`'s `.topbar` and `.brand`, which is expected. The screen rules, for today's markup (Tasks 5, 6 and 7 replace them):

Create `web/src/styles/new.css`:

```css
/* New report and the project page (spec §5.1, §5.2), on the tokens. */
.panel {
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-2);
  background: var(--surface);
  padding: var(--space-3) var(--space-4);
  margin: var(--space-4) 0;
}

.panel h2 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-md);
}

.sources {
  list-style: none;
  padding: 0;
  margin: var(--space-2) 0;
}

.sources li {
  padding: var(--space-1) 0;
}
```

Create `web/src/styles/run.css`:

```css
/* Writing the report (spec §5.3), on the tokens. */
.badge.state-completed {
  border-color: var(--ok);
  color: var(--ok);
}

.badge.state-failed,
.badge.state-gate_rejected {
  border-color: var(--danger);
  color: var(--danger);
}

.badge.state-cancelled {
  border-color: var(--warn);
  color: var(--warn);
}

.timeline {
  list-style: none;
  padding: 0;
  margin: var(--space-4) 0;
  display: grid;
  gap: var(--space-1);
}

.timeline li {
  display: grid;
  grid-template-columns: 12rem 1fr;
  gap: var(--space-3);
  padding: var(--space-2);
  border-inline-start: 0.25rem solid var(--border);
}

.timeline li[data-status="done"] {
  border-color: var(--ok);
}

.timeline li[data-status="running"] {
  border-color: var(--accent);
  font-weight: 600;
}

.timeline li[data-status="failed"] {
  border-color: var(--danger);
}

.timeline li[data-status="pending"] .stage {
  color: var(--text-muted);
}
```

Create `web/src/styles/review.css`:

```css
/* Review (spec §5.4), on the tokens. */
.badge.ok,
.badge.verdict-pass {
  border-color: var(--ok);
  color: var(--ok);
}

.badge.warn {
  border-color: var(--warn);
  color: var(--warn);
}

.badge.verdict-fail {
  border-color: var(--danger);
  color: var(--danger);
}

.review-body {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(20rem, 2fr);
  gap: var(--space-4);
  align-items: start;
}

.report-frame {
  width: 100%;
  height: calc(100vh - 14rem);
  min-height: var(--frame-min-height);
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-2);
  background: var(--surface);
}

.tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: var(--border-width) solid var(--border);
}

.tabs [role="tab"] {
  background: none;
  border: none;
  border-bottom: 0.125rem solid transparent;
  border-radius: 0;
}

.tabs [role="tab"][aria-selected="true"] {
  border-bottom-color: var(--accent);
  font-weight: 600;
}

.tabpanel {
  padding: var(--space-3) 0;
}

.actions {
  margin: var(--space-2) 0 var(--space-4);
}

.downloads {
  margin-inline-start: auto;
}

.claims {
  list-style: none;
  padding: 0;
  margin: 0;
}

.claims .claim {
  display: block;
  width: 100%;
  text-align: start;
  background: none;
  border: var(--border-width) solid transparent;
}

.claims .claim:hover {
  background: var(--surface-2);
}

.claims .claim[aria-pressed="true"] {
  border-color: var(--accent);
  background: var(--selected);
}

.evidence blockquote {
  margin: var(--space-1) 0 var(--space-3);
  padding-inline-start: var(--space-3);
  border-inline-start: 0.1875rem solid var(--border);
}
```

`.sr-only` is now `base.css`'s `.visually-hidden`:

```diff
diff --git a/web/src/pages/run/StageTimeline.tsx b/web/src/pages/run/StageTimeline.tsx
index b13e044..ff1983d 100644
--- a/web/src/pages/run/StageTimeline.tsx
+++ b/web/src/pages/run/StageTimeline.tsx
@@ -56,7 +56,7 @@ export function StageTimeline({ progress }: { progress: RunProgress }) {
       {timelineRows(progress).map((row) => (
         <li key={row.stage} data-status={row.status}>
           <span className="stage">{row.label}</span>
-          <span className="sr-only">{STATUS_TEXT[row.status]}</span>
+          <span className="visually-hidden">{STATUS_TEXT[row.status]}</span>
           <span className="muted" dir="auto">
             {describe(row, progress)}
           </span>
```

- [ ] **Step 6: Load them, set the theme first, and the toggle**

```diff
diff --git a/web/index.html b/web/index.html
index 5a91eaa..53647a6 100644
--- a/web/index.html
+++ b/web/index.html
@@ -3,6 +3,7 @@
   <head>
     <meta charset="UTF-8" />
     <meta name="viewport" content="width=device-width, initial-scale=1.0" />
+    <script src="/theme-init.js"></script>
     <title>Corelata</title>
   </head>
   <body>
```

`web/src/main.tsx`:

```tsx
import "./fonts";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/new.css";
import "./styles/run.css";
import "./styles/review.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { makeQueryClient, Providers } from "./Providers";
import { routes } from "./routes";
import { applyTheme } from "./theme/theme";

applyTheme();

const router = createBrowserRouter(routes);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers client={makeQueryClient()}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
```

`public/theme-init.js` is a browser script for eslint:

```diff
diff --git a/web/eslint.config.js b/web/eslint.config.js
index 534fc2c..26191c3 100644
--- a/web/eslint.config.js
+++ b/web/eslint.config.js
@@ -16,5 +16,6 @@ export default tseslint.config(
       "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
     },
   },
+  { files: ["public/**/*.js"], languageOptions: { globals: globals.browser } },
   { files: ["*.config.{js,ts}", "e2e/**"], languageOptions: { globals: globals.node } },
 );
```

The toggle on today's top bar (copied from Coglossa's `Layout`; Task 4 rewrites the frame):

```diff
diff --git a/web/src/components/Layout.tsx b/web/src/components/Layout.tsx
index 8d9d86a..4c53684 100644
--- a/web/src/components/Layout.tsx
+++ b/web/src/components/Layout.tsx
@@ -1,9 +1,12 @@
 import { NavLink, Outlet } from "react-router";
 import { useInfo } from "../api/system";
+import { useTheme } from "../theme/theme";
 import { ErrorMessage } from "./ErrorMessage";
 
 export function Layout() {
   const info = useInfo();
+  const { theme, setChoice } = useTheme();
+  const dark = theme === "dark";
   return (
     <div className="app">
       <header className="topbar">
@@ -14,6 +17,14 @@ export function Layout() {
           <NavLink to="/new">New run</NavLink>
         </nav>
         <span className="muted who">{info.data?.user ? `Signed in as ${info.data.user}` : ""}</span>
+        <button
+          type="button"
+          className="quiet"
+          aria-label={dark ? "Switch to the light theme" : "Switch to the dark theme"}
+          onClick={() => setChoice(dark ? "light" : "dark")}
+        >
+          <span aria-hidden="true">{dark ? "☀" : "☾"}</span>
+        </button>
       </header>
       {info.error ? <ErrorMessage error={info.error} /> : null}
       <main>
```

- [ ] **Step 7: Run the tests, lint and build**

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: lint clean; 308 passed in 39 files (211 before; the contrast test alone is 72 cases), coverage at least 95% on all four; the build lists `assets/noto-sans-*-{400,700}-normal-*.woff2` and `.woff` files and `dist/theme-init.js`.

Run: `grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(' web/src/styles/*.css | grep -v tokens.css`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
cat > "$SCRATCH/m18-task1-commit.txt" <<'EOF'
feat(web): Coglossa's tokens, base and frame styles, theme before first paint, Noto Sans (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/package.json web/pnpm-lock.yaml web/index.html web/eslint.config.js web/public/theme-init.js web/src/main.tsx web/src/fonts.ts web/src/fonts.test.ts web/src/styles web/src/theme web/src/test/jsdom-env.ts web/src/test/jsdom-storage.ts web/src/test/jsdom-storage.test.ts web/src/test/setup.ts web/src/components/Layout.tsx web/src/components/Layout.test.tsx web/src/pages/run/StageTimeline.tsx
git -C "$REPO" commit -F "$SCRATCH/m18-task1-commit.txt"
```

(`$REPO` is the worktree, `$SCRATCH` the session scratchpad; `git rm` in Step 5 staged the deletion.)

---

### Task 2: Coglossa's Dialog, Menu, StatusText and the date and key helpers

**Files:**
- Copy from Coglossa: `web/src/components/Dialog.tsx`, `web/src/components/Menu.tsx`, `web/src/components/Menu.test.tsx`, `web/src/components/StatusText.tsx`, `web/src/components/StatusText.test.tsx`, `web/src/lib/dates.ts`, `web/src/lib/dates.test.ts`, `web/src/lib/keys.ts`, `web/src/lib/keys.test.ts`
- Create: `web/src/components/Dialog.test.tsx`, `web/src/lib/status.ts`
- Modify: `web/src/components/ConfirmDialog.tsx`

**Interfaces:**
- Consumes: Task 1's `dialog.dialog`, `.menu`, `.menu-list`, `.status`, `.tone-*` classes.
- Produces: `Dialog({open, label, onClose, className = "dialog", children})`; `Menu({label, button, className?, children: (close: () => void) => ReactNode})` (items are `role="menuitem"` elements; arrow keys, Home, End, Esc, focus back to the button); `StatusText({status})`; `lib/status.ts`: `type Tone = "ok" | "warn" | "busy" | "bad" | "none"`, `type Status = {text, symbol, tone}`; `lib/dates.ts`: `dateGroup()`, `groupByDate()`, `whenText(iso, now?, locale?)`; `lib/keys.ts`: `keyBelongsToControl(target, key)`.

- [ ] **Step 1: Copy the tests and write Dialog's**

Copy `$COGLOSSA/web/src/components/Menu.test.tsx`, `$COGLOSSA/web/src/components/StatusText.test.tsx`, `$COGLOSSA/web/src/lib/dates.test.ts` and `$COGLOSSA/web/src/lib/keys.test.ts` to the same paths under `web/`:

`Menu.test.tsx`: _(identical to Coglossa's: copy it as it is)_
`StatusText.test.tsx`: _(identical to Coglossa's: copy it as it is)_
`dates.test.ts`: _(identical to Coglossa's: copy it as it is)_
`keys.test.ts`: _(identical to Coglossa's: copy it as it is)_

Coglossa has no test of its own for `Dialog`; Corelata's gate needs one. Create `web/src/components/Dialog.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { Dialog } from "./Dialog";

it("shows its children only while open, and Esc asks the parent instead of closing", () => {
  const onClose = vi.fn();
  const { rerender } = render(
    <Dialog open label="Help" onClose={onClose}>
      <p>Inside</p>
    </Dialog>,
  );
  const dialog = screen.getByRole("dialog", { name: "Help" });
  expect(dialog).toHaveAttribute("open");
  expect(dialog).toHaveClass("dialog");
  const escape = new Event("cancel", { cancelable: true });
  fireEvent(dialog, escape);
  expect(escape.defaultPrevented).toBe(true); // the parent decides
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(dialog).toHaveAttribute("open");
  rerender(
    <Dialog open={false} label="Help" onClose={onClose} className="dialog help">
      <p>Inside</p>
    </Dialog>,
  );
  expect(dialog).not.toHaveAttribute("open");
  expect(dialog).toHaveClass("dialog", "help");
  expect(screen.queryByText("Inside")).toBeNull();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/components/Dialog.test.tsx src/components/Menu.test.tsx src/components/StatusText.test.tsx src/lib/dates.test.ts src/lib/keys.test.ts`
Expected: FAIL: `Failed to resolve import "./Dialog"`, `"./Menu"`, `"./StatusText"`, `"./dates"`, `"./keys"`.

- [ ] **Step 3: Copy the components and helpers**

`web/src/components/Dialog.tsx` from `$COGLOSSA/web/src/components/Dialog.tsx`: 

```diff
--- coglossa/web/src/components/Dialog.tsx
+++ corelata/web/src/components/Dialog.tsx
@@ -8,8 +8,8 @@
   children: ReactNode;
 };
 
-/** Spec §7.4: a modal <dialog>. The browser traps focus; Esc asks onClose, so a parent can
- * refuse (unsaved changes). Children render only while it is open. */
+/** Copied from Coglossa (spec §2.2): a modal <dialog>. The browser traps focus; Esc asks onClose,
+ * so a parent can refuse. Children render only while it is open. */
 export function Dialog({ open, label, onClose, className = "dialog", children }: Props) {
   const ref = useRef<HTMLDialogElement>(null);
   useEffect(() => {
```


`web/src/components/Menu.tsx` from `$COGLOSSA/web/src/components/Menu.tsx` (R-M18-9: Corelata keeps `react-hooks/refs` on):



```diff
--- coglossa/web/src/components/Menu.tsx
+++ corelata/web/src/components/Menu.tsx
@@ -7,7 +7,8 @@
   children: (close: () => void) => ReactNode;
 };
 
-/** Plan decision 4: a button that opens a list of actions; Esc or a click outside closes it. */
+/** Copied from Coglossa (spec §2.2): a button that opens a list of actions; Esc or a click
+ * outside closes it. */
 export function Menu({ label, button, className, children }: Props) {
   const [open, setOpen] = useState(false);
   const ref = useRef<HTMLDivElement>(null);
@@ -103,6 +104,9 @@
       </button>
       {open ? (
         <div id={id} role="menu" aria-label={label} className="menu-list">
+          {/* close() reads the button's ref only when an item calls it, from an event handler.
+              Coglossa turns this rule off for the whole app; Corelata keeps it (R-M18-9). */}
+          {/* eslint-disable-next-line react-hooks/refs */}
           {children(close)}
         </div>
       ) : null}
```


`web/src/components/StatusText.tsx` from `$COGLOSSA/web/src/components/StatusText.tsx`; its `Status` type comes from `lib/status.ts`, which here holds only the type (Task 4 adds the functions):



```diff
--- coglossa/web/src/components/StatusText.tsx
+++ corelata/web/src/components/StatusText.tsx
@@ -1,6 +1,7 @@
 import type { Status } from "../lib/status";
 
-/** A status in words, with its symbol, coloured by tone (never colour alone). */
+/** Copied from Coglossa (spec §2.2): a status in words, with its symbol, coloured by tone (never
+ * colour alone). */
 export function StatusText({ status }: { status: Status }) {
   return (
     <span className={`status tone-${status.tone}`}>
```


Create `web/src/lib/status.ts`:

```ts
/** Copied from Coglossa's lib/status.ts (spec §2.2): the tone classes are base.css's `tone-*`. */
export type Tone = "ok" | "warn" | "busy" | "bad" | "none";
/** A status always carries words, and a symbol where it has one; never colour alone. */
export type Status = { text: string; symbol: string; tone: Tone };
```

`web/src/lib/dates.ts` from `$COGLOSSA/web/src/lib/dates.ts`: 

```diff
--- coglossa/web/src/lib/dates.ts
+++ corelata/web/src/lib/dates.ts
@@ -1,3 +1,4 @@
+// Copied from Coglossa unchanged (spec §2.2).
 export type DateGroup = "Today" | "This week" | "Earlier";
 const DAY_MS = 24 * 3600_000;
 const ORDER: DateGroup[] = ["Today", "This week", "Earlier"];
```


`web/src/lib/keys.ts` from `$COGLOSSA/web/src/lib/keys.ts`: 

```diff
--- coglossa/web/src/lib/keys.ts
+++ corelata/web/src/lib/keys.ts
@@ -1,3 +1,4 @@
+// Copied from Coglossa unchanged (spec §2.2).
 const ACTIVATABLE = "button, a[href], summary, [role=button], input";
 const NOT_TEXT_INPUT = ["checkbox", "radio", "button", "submit", "reset", "image", "file"];
```


`ConfirmDialog` (Corelata's, kept) gives its confirm button the primary style unless it is a danger:

```diff
diff --git a/web/src/components/ConfirmDialog.tsx b/web/src/components/ConfirmDialog.tsx
index 5983d2a..c74a1be 100644
--- a/web/src/components/ConfirmDialog.tsx
+++ b/web/src/components/ConfirmDialog.tsx
@@ -58,7 +58,7 @@ export function ConfirmDialog({
         </button>
         <button
           type="button"
-          className={danger ? "danger" : ""}
+          className={danger ? "danger" : "primary"}
           onClick={onConfirm}
           disabled={busy || confirmDisabled}
         >
```

- [ ] **Step 4: Run the tests and lint**

Run: `cd web && pnpm lint && pnpm test`
Expected: lint clean (it fails on `Menu.tsx` line `{children(close)}` without the disable line); 322 passed in 44 files, coverage at least 95%.

- [ ] **Step 5: Commit**

```bash
cat > "$SCRATCH/m18-task2-commit.txt" <<'EOF'
feat(web): Coglossa's Dialog, Menu, StatusText, dates and keys (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/src/components/Dialog.tsx web/src/components/Dialog.test.tsx web/src/components/Menu.tsx web/src/components/Menu.test.tsx web/src/components/StatusText.tsx web/src/components/StatusText.test.tsx web/src/components/ConfirmDialog.tsx web/src/lib/dates.ts web/src/lib/dates.test.ts web/src/lib/keys.ts web/src/lib/keys.test.ts web/src/lib/status.ts
git -C "$REPO" commit -F "$SCRATCH/m18-task2-commit.txt"
```

---

### Task 3: The project summary, the run list's decision, the sign-out page (spec §7)

**Files:**
- Create: `engine/tests/store/test_project_summaries.py`
- Modify: `engine/corelata/schema/progress.py`, `engine/corelata/schema/__init__.py`, `engine/corelata/store/runs.py`, `engine/corelata/service.py`, `engine/corelata/config.py`, `engine/corelata.example.yaml`, `deploy/config/corelata.example.yaml`, `engine/tests/test_config.py`, `api/corelata_api/routes/projects.py`, `api/corelata_api/routes/system.py`, `api/tests/test_projects.py`, `api/tests/test_app.py`, `schema/openapi.json`, `schema/run-summary.schema.json`, `web/src/api/schema.d.ts`, `web/src/api/types.ts`, `web/src/test/fixtures.ts`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `corelata.schema.LatestRun {run_id: str, state: RunState, status: ReportStatus | None, decision: ReviewDecision | None}`; `ProjectSummary {last_activity_at: datetime, reports_writing: int, reports_to_review: int, latest_run: LatestRun | None}`; `RunSummary.review_decision: ReviewDecision | None`, `RunSummary.review_child_state: RunState | None`; `store.runs.project_summaries(s, project_id=None) -> list[tuple[Project, ProjectSummary]]`, `store.runs.FREED_BY`; `service.list_project_summaries(db)`, `service.get_project_summary(db, project_id)` (raises `NotFoundError`), `service.new_project_summary(project)`; `AuthConfig.logout_url: str | None`; API: `ProjectView` = `{id, name, created_at, last_activity_at, reports_writing, reports_to_review, latest_run}` on all three project routes, `SystemInfo.logout_url`; web types `ProjectView`, `LatestRun`, `RunSummary` with the new fields; the `project` fixture with an empty summary.

- [ ] **Step 1: Write the failing tests**

Create `engine/tests/store/test_project_summaries.py`:

```python
"""The sidebar's project summaries (M18 spec §7.1, R-M18-3) and the run list's decision (§7.2)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event

from corelata import service
from corelata.store import runs
from tests.store.test_runs import T0, _project_with_source, _run


def _review(decision: str, child_state: str | None = None) -> dict:
    """A stored ReviewState (`service._review_state`'s shape)."""
    return {
        "decision": decision,
        "at": "2026-10-20T10:00:00Z",
        "actor": "ana",
        "child_run_id": str(uuid.uuid4()) if decision == "returned" else None,
        "child_state": child_state,
        "child_error": None,
        "note": "n" if decision == "returned" else None,
    }


async def _runs_in(s, project, source, rows: list[tuple[str, dict | None]]) -> list[uuid.UUID]:
    """One run per (state, review_state), created a minute apart in that order from T0; a
    terminal run finished 30 s after it was created. The project and its source are an hour
    older than the first run."""
    project.created_at = source.created_at = T0 - timedelta(hours=1)
    ids = []
    for i, (state, review) in enumerate(rows):
        run = await _run(s, project, [source], created_at=T0 + timedelta(minutes=i))
        run.state = state
        run.review_state = review
        if state in ("completed", "gate_rejected", "failed", "cancelled"):
            run.finished_at = T0 + timedelta(minutes=i, seconds=30)
        ids.append(run.id)
    await s.flush()
    return ids


async def test_the_summary_counts_writing_and_to_review_and_finds_the_newest_run(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s, "mixed")
        ids = await _runs_in(
            s,
            project,
            source,
            [
                ("completed", None),  # to review
                ("completed", _review("accepted")),  # decided
                ("completed", _review("returned", "failed")),  # its revision failed: to review
                ("completed", _review("returned", "gate_rejected")),  # to review
                ("completed", _review("returned", "cancelled")),  # to review
                ("completed", _review("returned", None)),  # its revision is being written
                ("completed", _review("returned", "completed")),  # revised: nothing to review
                ("failed", None),
                ("gate_rejected", None),
                ("drafting", None),  # writing
                ("created", None),  # writing, and the newest
            ],
        )
    async with db.session() as s:
        [(found, summary)] = await runs.project_summaries(s)
    assert found.id == project.id
    assert (summary.reports_writing, summary.reports_to_review) == (2, 4)
    assert summary.latest_run is not None
    assert (summary.latest_run.run_id, summary.latest_run.state) == (str(ids[-1]), "created")
    # the newest stamp: the newest run's created_at (+10 min), after every finished_at
    assert summary.last_activity_at == T0 + timedelta(minutes=10)


async def test_a_finish_after_the_newest_creation_is_the_last_activity(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        await _runs_in(s, project, source, [("completed", None)])
    async with db.session() as s:
        [(_, summary)] = await runs.project_summaries(s)
    assert summary.last_activity_at == T0 + timedelta(seconds=30)


async def test_an_empty_project_and_a_project_with_sources_only(db):
    async with db.session() as s, s.begin():
        empty = await runs.get_or_create_project(s, "empty")
        sourced, source = await _project_with_source(s, "sources only")
        source.created_at = sourced.created_at + timedelta(hours=1)
        await s.flush()
    async with db.session() as s:
        summaries = {p.name: summary for p, summary in await runs.project_summaries(s)}
    assert summaries["empty"].model_dump() == {
        "last_activity_at": empty.created_at,
        "reports_writing": 0,
        "reports_to_review": 0,
        "latest_run": None,
    }
    assert summaries["sources only"].last_activity_at == source.created_at
    assert summaries["sources only"].latest_run is None
    assert service.new_project_summary(empty) == summaries["empty"]


async def test_the_latest_run_carries_its_status_and_decision_and_breaks_a_tie_by_id(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        ids = await _runs_in(s, project, source, [("completed", None), ("completed", None)])
        for run_id in ids:  # the same microsecond: the larger id is the newer (CRL-24)
            run = await runs.get_run(s, run_id)
            run.created_at, run.status, run.review_state = T0, "clean", _review("accepted")
    async with db.session() as s:
        [(_, summary)] = await runs.project_summaries(s)
    assert summary.latest_run is not None
    assert summary.latest_run.model_dump() == {
        "run_id": str(max(ids)),
        "state": "completed",
        "status": "clean",
        "decision": "accepted",
    }
    assert summary.reports_to_review == 0


async def test_the_summaries_take_three_statements_however_many_projects(db):
    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    made = 0
    for n in (1, 20):
        async with db.session() as s, s.begin():
            while made < n:
                project, source = await _project_with_source(s, f"p{made}")
                await _runs_in(s, project, source, [("completed", None), ("drafting", None)])
                made += 1
        event.listen(db.engine.sync_engine, "before_cursor_execute", count)
        try:
            async with db.session() as s:
                found = await runs.project_summaries(s)
        finally:
            event.remove(db.engine.sync_engine, "before_cursor_execute", count)
        assert len(found) == n
        assert all(summary.reports_writing == 1 for _, summary in found)
        assert len(statements) == 3, statements
        statements.clear()


async def test_one_projects_summary_and_a_missing_project(db):
    async with db.session() as s, s.begin():
        a, source = await _project_with_source(s, "a")
        await _runs_in(s, a, source, [("drafting", None)])
        await _project_with_source(s, "b")
    async with db.session() as s:
        [(found, summary)] = await runs.project_summaries(s, a.id)
        assert (found.name, summary.reports_writing) == ("a", 1)
        assert await runs.project_summaries(s, uuid.uuid4()) == []
    assert (await service.get_project_summary(db, a.id))[1].reports_writing == 1
    assert [p.name for p, _ in await service.list_project_summaries(db)] == ["a", "b"]
    with pytest.raises(runs.NotFoundError, match="not found"):
        await service.get_project_summary(db, uuid.uuid4())


def test_the_summary_frees_a_return_by_the_services_rule():
    assert runs.FREED_BY == service.FREED_BY  # R-M15-1: failed, cancelled, gate_rejected


async def test_a_run_summary_carries_the_stored_decision_and_the_revisions_end(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        await _runs_in(
            s, project, source, [("completed", None), ("completed", _review("returned", "failed"))]
        )
    newest, oldest = await service.list_runs(db, project.id)
    assert (newest.review_decision, newest.review_child_state) == ("returned", "failed")
    assert (oldest.review_decision, oldest.review_child_state) == (None, None)
```

`auth.logout_url` is operational, like the rest of `auth`:

```diff
diff --git a/engine/tests/test_config.py b/engine/tests/test_config.py
index 562c293..e0ebba4 100644
--- a/engine/tests/test_config.py
+++ b/engine/tests/test_config.py
@@ -155,7 +155,11 @@ def test_load_non_mapping(tmp_path):
 
 def test_config_hash_ignores_operational_sections(make_config):
     a = make_config()
-    b = make_config(api={"web_dir": None}, worker={"concurrency": 7}, auth={"mode": "none"})
+    b = make_config(
+        api={"web_dir": None},
+        worker={"concurrency": 7},
+        auth={"mode": "none", "logout_url": "/oauth2/sign_out"},  # M18: operational too
+    )
     c = make_config(pipeline={"max_iterations": 3})
     assert config_hash(a) == config_hash(b)
     assert config_hash(a) != config_hash(c)
```

The API's three project routes, the run list and the info route:

```diff
diff --git a/api/tests/test_projects.py b/api/tests/test_projects.py
index bc008dc..1dd42d2 100644
--- a/api/tests/test_projects.py
+++ b/api/tests/test_projects.py
@@ -1,7 +1,8 @@
 import json
 import uuid
+from datetime import datetime
 
-from tests.conftest import coglossa_export
+from tests.conftest import STATEMENT, coglossa_export, project_with_source, set_run_state
 
 PORT_TEXT = (
     "The port of Varna handles grain, containers and general cargo.\n\n"
@@ -27,6 +28,10 @@ async def _upload(api, project_id, filename, data: bytes, **form) -> object:
 async def test_create_list_and_get_projects(api):
     project = await _project(api)
     assert project["name"] == "Black Sea" and uuid.UUID(project["id"]) and project["created_at"]
+    # a new project has nothing to summarise yet (M18 spec §7.1)
+    assert project["last_activity_at"] == project["created_at"]
+    assert (project["reports_writing"], project["reports_to_review"]) == (0, 0)
+    assert project["latest_run"] is None
     assert (await api.client.get("/api/projects")).json() == [project]
     assert (await api.client.get(f"/api/projects/{project['id']}")).json() == project
     duplicate = await api.client.post("/api/projects", json={"name": "Black Sea"})
@@ -95,3 +100,33 @@ async def test_upload_too_large_leaves_no_file(make_api):
         )
         assert not list(api.storage_root.rglob("*"))
         assert (await api.client.get(f"/api/projects/{project['id']}/sources")).json() == []
+
+
+async def test_projects_carry_the_sidebar_summary_and_runs_their_decision(api):
+    """M18 spec §7.1 and §7.2: the list, one project and the run list agree."""
+    pid, sid = await project_with_source(api, "summary")
+    body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
+    first = (await api.client.post("/api/runs", json=body)).json()
+    second = (await api.client.post("/api/runs", json=body)).json()
+    await set_run_state(api.db, first["run_id"], "completed")
+    to_review = (await api.client.get(f"/api/projects/{pid}")).json()
+    assert (to_review["reports_writing"], to_review["reports_to_review"]) == (1, 1)
+    accept = await api.client.post(f"/api/runs/{first['run_id']}/review", json={"action": "accept"})
+    assert accept.status_code == 200, accept.text
+    [view] = [p for p in (await api.client.get("/api/projects")).json() if p["id"] == pid]
+    assert (view["reports_writing"], view["reports_to_review"]) == (1, 0)
+    assert view["latest_run"] == {
+        "run_id": second["run_id"],
+        "state": "created",
+        "status": None,
+        "decision": None,
+    }
+    assert datetime.fromisoformat(view["last_activity_at"]) >= datetime.fromisoformat(
+        second["created_at"]
+    )
+    assert (await api.client.get(f"/api/projects/{pid}")).json() == view
+    page = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]
+    assert [(r["review_decision"], r["review_child_state"]) for r in page] == [
+        (None, None),
+        ("accepted", None),
+    ]
```

```diff
diff --git a/api/tests/test_app.py b/api/tests/test_app.py
index 1c2dec9..c4fbb13 100644
--- a/api/tests/test_app.py
+++ b/api/tests/test_app.py
@@ -75,6 +75,15 @@ async def test_auth_none_has_no_user(api):
     assert body["user"] is None and body["auth_mode"] == "none"
     assert body["coglossa"] is False and body["default_pack"] == "icd203-base"
     assert body["version"] == corelata.__version__ and body["max_upload_mb"] == 200
+    assert body["logout_url"] is None  # no Sign out on the air-gapped install (M18 spec §7.3)
+
+
+async def test_info_reports_the_proxys_sign_out_page(make_api):
+    auth = {"mode": "trusted_header", "logout_url": "/oauth2/sign_out"}
+    async with make_api(auth=auth) as api:
+        response = await api.client.get("/api/system/info", headers={"X-Remote-User": "ana"})
+    assert response.status_code == 200
+    assert response.json()["logout_url"] == "/oauth2/sign_out"
 
 
 async def test_openapi_is_behind_auth_and_the_doc_pages_are_off(make_api):
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/store/test_project_summaries.py tests/test_config.py --no-cov -q`
Expected: FAIL: `AttributeError: module 'corelata.store.runs' has no attribute 'project_summaries'` (and `FREED_BY`, `get_project_summary`, `review_decision`), and the config test's `extra_forbidden` for `auth.logout_url`.

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_projects.py tests/test_app.py --no-cov -q`
Expected: FAIL: `KeyError: 'last_activity_at'`, `KeyError: 'logout_url'`.

- [ ] **Step 3: The models**

```diff
diff --git a/engine/corelata/schema/progress.py b/engine/corelata/schema/progress.py
index c65b97f..f4b7843 100644
--- a/engine/corelata/schema/progress.py
+++ b/engine/corelata/schema/progress.py
@@ -71,6 +71,41 @@ class RunSummary(BaseModel):
     max_iterations: int
     created_at: datetime
     finished_at: datetime | None = None
+    # The stored decision (`RunProgress.review`), so a list shows "accepted" or "returned"
+    # without a request per row (M18 spec §7.2), and the revision's end, so it shows a return
+    # whose revision ended without a report as "to review" again (R-M15-1, R-M18-7).
+    review_decision: ReviewDecision | None = None
+    review_child_state: RunState | None = None
+
+
+class LatestRun(BaseModel):
+    """A project's newest run by `(created_at, id)` (M18 spec §7.1)."""
+
+    run_id: str
+    state: RunState
+    status: ReportStatus | None = None
+    decision: ReviewDecision | None = None
+
+
+class ProjectSummary(BaseModel):
+    """What the sidebar shows for a project (M18 spec §7.1, R-M18-3): computed for the whole
+    list by a fixed number of grouped queries, whatever its length (`store.runs`)."""
+
+    last_activity_at: datetime = Field(
+        description=(
+            "The latest of the project's `created_at`, its sources' `created_at`, and its runs' "
+            "`created_at` and `finished_at`."
+        )
+    )
+    reports_writing: int = Field(0, description="Runs not in a terminal state.")
+    reports_to_review: int = Field(
+        0,
+        description=(
+            "Completed runs with no decision, or whose return's revision ended without a "
+            "report (failed, cancelled or not supported; R-M15-1)."
+        ),
+    )
+    latest_run: LatestRun | None = None
 
 
 class DiscoveryState(StrEnum):
```

```diff
diff --git a/engine/corelata/schema/__init__.py b/engine/corelata/schema/__init__.py
index 67f4a59..161d47f 100644
--- a/engine/corelata/schema/__init__.py
+++ b/engine/corelata/schema/__init__.py
@@ -32,6 +32,8 @@ from corelata.schema.profiler import DraftLimits, DraftRuleOverride, ProfileDraf
 from corelata.schema.progress import (
     DiscoveryState,
     DiscoveryView,
+    LatestRun,
+    ProjectSummary,
     ReviewAction,
     ReviewDecision,
     ReviewState,
@@ -112,6 +114,8 @@ __all__ = [
     "ReviewState",
     "RunProgress",
     "RunSummary",
+    "LatestRun",
+    "ProjectSummary",
     "DiscoveryState",
     "DiscoveryView",
     "CheckStatus",
```

```diff
diff --git a/engine/corelata/config.py b/engine/corelata/config.py
index 18a5d50..0b4e228 100644
--- a/engine/corelata/config.py
+++ b/engine/corelata/config.py
@@ -169,6 +169,9 @@ class AuthConfig(_Strict):
 
     mode: Literal["none", "trusted_header"] = "none"
     header: str = "X-Remote-User"
+    # the proxy's own sign-out page: the web app's header shows "Sign out" and posts there
+    # (copied from Coglossa, M18 spec §7.3); unset, no Sign out is shown
+    logout_url: str | None = None
 
     @field_validator("header")
     @classmethod
```

```diff
diff --git a/engine/corelata.example.yaml b/engine/corelata.example.yaml
index 02f6a63..38a6196 100644
--- a/engine/corelata.example.yaml
+++ b/engine/corelata.example.yaml
@@ -52,6 +52,6 @@ worker:
 api: { max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64 } # upload limit; SSE poll interval; claim-id render memory
 # api: { ..., web_dir: ../web/dist }     # serve the built web app from the API; or corelata-api --web-dir
 auth: { mode: none }                             # none: anyone who reaches the API; trusted_header: a proxy signs people in
-# auth: { mode: trusted_header, header: X-Remote-User }
+# auth: { mode: trusted_header, header: X-Remote-User, logout_url: /oauth2/sign_out }
 # integrations:
 #   coglossa: { base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY }
```

```diff
diff --git a/deploy/config/corelata.example.yaml b/deploy/config/corelata.example.yaml
index 44998ee..106687a 100644
--- a/deploy/config/corelata.example.yaml
+++ b/deploy/config/corelata.example.yaml
@@ -45,7 +45,7 @@ worker:
   discovery_start_deadline_s: 3600  # seconds a discovery may wait for the worker to start it
 api: { max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64 }
 auth: { mode: none }               # trusted_header when a reverse proxy signs people in (operator guide)
-# auth: { mode: trusted_header, header: X-Remote-User }
+# auth: { mode: trusted_header, header: X-Remote-User, logout_url: /oauth2/sign_out }
 # integrations:
 #   coglossa: { base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY }
 # The database is set by the containers (CORELATA_DATABASE_URL); do not add a database section.
```

- [ ] **Step 4: Three statements for the whole list (R-M18-17)**

```diff
diff --git a/engine/corelata/store/runs.py b/engine/corelata/store/runs.py
index aaf7e8d..ff91872 100644
--- a/engine/corelata/store/runs.py
+++ b/engine/corelata/store/runs.py
@@ -9,17 +9,20 @@ from collections.abc import Iterable
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import delete, null, select, text, tuple_, update
+from sqlalchemy import and_, delete, func, null, or_, select, text, tuple_, update
 from sqlalchemy.dialects.postgresql import insert as pg_insert
 from sqlalchemy.exc import DBAPIError, SQLAlchemyError
 from sqlalchemy.ext.asyncio import AsyncSession
 from sqlalchemy.orm import defer
 
 from corelata.schema import (
+    TERMINAL_STATES,
     BlockKind,
     DraftRecord,
     Finding,
+    LatestRun,
     LLMCallRecord,
+    ProjectSummary,
     Report,
     RunState,
     Source,
@@ -112,6 +115,97 @@ async def list_projects(s: AsyncSession) -> list[Project]:
     return list(await s.scalars(select(Project).order_by(Project.created_at, Project.name)))
 
 
+# A return whose revision ended in one of these produced no report, so the run is to review
+# again (R-M15-1); the same set as `service.FREED_BY`, which a test pins.
+FREED_BY = TERMINAL_STATES - {RunState.COMPLETED}
+_TERMINAL = sorted(state.value for state in TERMINAL_STATES)
+_FREED = sorted(state.value for state in FREED_BY)
+
+
+def _review_field(name: str) -> Any:
+    """A field of the stored `ReviewState` JSON as text; NULL when the run has none."""
+    return func.jsonb_extract_path_text(Run.review_state, name)
+
+
+# Each project's newest run, by the run list's order (CRL-24), which `ix_run_project_created`
+# serves. Written out: SQLAlchemy 2.1 deprecates `.distinct(column)` for DISTINCT ON, and its
+# replacement does not exist in 2.0, which the engine's dependency floor still allows.
+_LATEST_RUN = (
+    "SELECT DISTINCT ON (project_id) project_id, id, state, status, "
+    "review_state->>'decision' AS decision FROM run {where}"
+    "ORDER BY project_id, created_at DESC, id DESC"
+)
+
+
+def _to_review() -> Any:
+    """A completed run nobody decided on, or whose return's revision ended without a report."""
+    decision = _review_field("decision")
+    freed = and_(decision == "returned", _review_field("child_state").in_(_FREED))
+    return and_(Run.state == RunState.COMPLETED.value, or_(decision.is_(None), freed))
+
+
+async def project_summaries(
+    s: AsyncSession, project_id: uuid.UUID | None = None
+) -> list[tuple[Project, ProjectSummary]]:
+    """Every project (or the one `project_id` names) with its summary, in `list_projects`'s
+    order: three statements whatever the number of projects, never one per project (M18 spec
+    §7.1, R-M18-3). (1) the projects with their newest source's `created_at`; (2) one aggregate
+    over `run` grouped by project, with FILTER clauses; (3) each project's newest run by
+    `DISTINCT ON (project_id)`, which `ix_run_project_created` serves."""
+    newest_source = (
+        select(SourceRow.project_id, func.max(SourceRow.created_at).label("at"))
+        .group_by(SourceRow.project_id)
+        .subquery()
+    )
+    projects = (
+        select(Project, newest_source.c.at)
+        .outerjoin(newest_source, newest_source.c.project_id == Project.id)
+        .order_by(Project.created_at, Project.name)
+    )
+    counts = select(
+        Run.project_id,
+        func.count().filter(Run.state.not_in(_TERMINAL)).label("writing"),
+        func.count().filter(_to_review()).label("to_review"),
+        func.max(Run.created_at).label("created"),
+        func.max(Run.finished_at).label("finished"),
+    ).group_by(Run.project_id)
+    where = ""
+    if project_id is not None:
+        projects = projects.where(Project.id == project_id)
+        counts = counts.where(Run.project_id == project_id)
+        where = "WHERE project_id = :project_id "
+    latest = text(_LATEST_RUN.format(where=where))
+    rows = (await s.execute(projects)).all()
+    by_project = {r.project_id: r for r in await s.execute(counts)}
+    newest = {r.project_id: r for r in await s.execute(latest, {"project_id": project_id})}
+    found: list[tuple[Project, ProjectSummary]] = []
+    for project, source_at in rows:
+        count = by_project.get(project.id)
+        run = newest.get(project.id)
+        stamps = [project.created_at, source_at]
+        if count is not None:
+            stamps += [count.created, count.finished]
+        found.append(
+            (
+                project,
+                ProjectSummary(
+                    last_activity_at=max(t for t in stamps if t is not None),
+                    reports_writing=count.writing if count else 0,
+                    reports_to_review=count.to_review if count else 0,
+                    latest_run=LatestRun(
+                        run_id=str(run.id),
+                        state=RunState(run.state),
+                        status=run.status,
+                        decision=run.decision,
+                    )
+                    if run
+                    else None,
+                ),
+            )
+        )
+    return found
+
+
 async def delete_project(s: AsyncSession, project_id: uuid.UUID) -> None:
     await s.delete(await get_project(s, project_id))
     await s.flush()
```

- [ ] **Step 5: The service and the routes**

```diff
diff --git a/engine/corelata/service.py b/engine/corelata/service.py
index 2b29f70..f8dd656 100644
--- a/engine/corelata/service.py
+++ b/engine/corelata/service.py
@@ -26,6 +26,7 @@ from corelata.schema import (
     TERMINAL_STATES,
     DiscoveryState,
     DiscoveryView,
+    ProjectSummary,
     ReviewAction,
     ReviewDecision,
     ReviewState,
@@ -210,6 +211,27 @@ async def list_projects(db: Database) -> list[Project]:
         return await runs.list_projects(s)
 
 
+async def list_project_summaries(db: Database) -> list[tuple[Project, ProjectSummary]]:
+    """`GET /api/projects`: every project with what the sidebar shows (M18 spec §7.1)."""
+    async with db.session() as s:
+        return await runs.project_summaries(s)
+
+
+async def get_project_summary(
+    db: Database, project_id: uuid.UUID
+) -> tuple[Project, ProjectSummary]:
+    async with db.session() as s:
+        found = await runs.project_summaries(s, project_id)
+    if not found:
+        raise runs.NotFoundError(f"project {project_id} not found")
+    return found[0]
+
+
+def new_project_summary(project: Project) -> ProjectSummary:
+    """A project just created has no sources and no runs."""
+    return ProjectSummary(last_activity_at=project.created_at)
+
+
 async def list_sources(db: Database, project_id: uuid.UUID) -> list[SourceRow]:
     async with db.session() as s:
         await runs.get_project(s, project_id)
@@ -616,6 +638,7 @@ async def run_progress(db: Database, run_id: uuid.UUID) -> RunProgress:
 
 
 def _summary(run: Run) -> RunSummary:
+    review = run.review_state or {}
     return RunSummary(
         run_id=str(run.id),
         project_id=str(run.project_id),
@@ -628,6 +651,8 @@ def _summary(run: Run) -> RunSummary:
         max_iterations=run.max_iterations,
         created_at=run.created_at,
         finished_at=run.finished_at,
+        review_decision=review.get("decision"),
+        review_child_state=review.get("child_state"),
     )
```

```diff
diff --git a/api/corelata_api/routes/projects.py b/api/corelata_api/routes/projects.py
index b3cf7e2..cd85fc0 100644
--- a/api/corelata_api/routes/projects.py
+++ b/api/corelata_api/routes/projects.py
@@ -5,7 +5,7 @@ from datetime import datetime
 from typing import Annotated, Any
 
 from corelata import service
-from corelata.schema import SourceKind
+from corelata.schema import LatestRun, ProjectSummary, SourceKind
 from corelata.store.models import Project, SourceRow
 from fastapi import APIRouter, Form, UploadFile
 from pydantic import BaseModel, Field
@@ -21,13 +21,24 @@ class CreateProject(BaseModel):
 
 
 class ProjectView(BaseModel):
+    """A project and what the sidebar shows for it (M18 spec §7.1)."""
+
     id: str
     name: str
     created_at: datetime
+    last_activity_at: datetime
+    reports_writing: int
+    reports_to_review: int
+    latest_run: LatestRun | None
 
     @classmethod
-    def of(cls, project: Project) -> "ProjectView":
-        return cls(id=str(project.id), name=project.name, created_at=project.created_at)
+    def of(cls, project: Project, summary: ProjectSummary) -> "ProjectView":
+        return cls(
+            id=str(project.id),
+            name=project.name,
+            created_at=project.created_at,
+            **summary.model_dump(),
+        )
 
 
 class SourceView(BaseModel):
@@ -62,17 +73,18 @@ async def source_views(ctx: Ctx, project_id: uuid.UUID, ids: list[uuid.UUID]) ->
 
 @router.get("/projects")
 async def list_projects(ctx: Ctx) -> list[ProjectView]:
-    return [ProjectView.of(p) for p in await service.list_projects(ctx.db)]
+    return [ProjectView.of(p, s) for p, s in await service.list_project_summaries(ctx.db)]
 
 
 @router.post("/projects", status_code=201)
 async def create_project(body: CreateProject, ctx: Ctx) -> ProjectView:
-    return ProjectView.of(await service.new_project(ctx.db, body.name))
+    project = await service.new_project(ctx.db, body.name)
+    return ProjectView.of(project, service.new_project_summary(project))
 
 
 @router.get("/projects/{project_id}")
 async def get_project(project_id: uuid.UUID, ctx: Ctx) -> ProjectView:
-    return ProjectView.of(await service.get_project(ctx.db, project_id))
+    return ProjectView.of(*await service.get_project_summary(ctx.db, project_id))
 
 
 @router.get("/projects/{project_id}/sources")
```

```diff
diff --git a/api/corelata_api/routes/system.py b/api/corelata_api/routes/system.py
index 8f31e39..1896a84 100644
--- a/api/corelata_api/routes/system.py
+++ b/api/corelata_api/routes/system.py
@@ -22,6 +22,7 @@ class SystemInfo(BaseModel):
     max_upload_mb: int
     default_pack: str
     default_profile: str | None
+    logout_url: str | None = None  # the proxy's sign-out page (auth.logout_url), or None
 
 
 @router.get("/system/info")
@@ -35,6 +36,7 @@ async def get_info(ctx: Ctx, user: User) -> SystemInfo:
         max_upload_mb=cfg.api.max_upload_mb,
         default_pack=cfg.standards.default_pack,
         default_profile=cfg.standards.default_profile,
+        logout_url=cfg.auth.logout_url,
     )
```

- [ ] **Step 6: Regenerate the schema and the web's types**

Run: `make schema`
Expected: `schema/openapi.json` (the four `ProjectView` fields, `LatestRun`, `RunSummary`'s two, `SystemInfo.logout_url`), `schema/run-summary.schema.json` and `web/src/api/schema.d.ts` change; nothing else. A second `make schema` changes nothing.

The web compiles against the new required fields:

```diff
diff --git a/web/src/api/types.ts b/web/src/api/types.ts
index ec3a858..30566b4 100644
--- a/web/src/api/types.ts
+++ b/web/src/api/types.ts
@@ -4,6 +4,7 @@ type S = components["schemas"];
 
 export type SystemInfo = S["SystemInfo"];
 export type ProjectView = S["ProjectView"];
+export type LatestRun = S["LatestRun"];
 export type SourceView = S["SourceView"];
 export type SourceKind = S["SourceKind"];
 export type RunProgress = S["RunProgress"];
```

```diff
diff --git a/web/src/test/fixtures.ts b/web/src/test/fixtures.ts
index 9b345f6..a140bcb 100644
--- a/web/src/test/fixtures.ts
+++ b/web/src/test/fixtures.ts
@@ -29,6 +29,10 @@ export const project: ProjectView = {
   id: "11111111-1111-1111-1111-111111111111",
   name: "Black Sea",
   created_at: "2026-10-13T10:00:00Z",
+  last_activity_at: "2026-10-13T10:00:00Z",
+  reports_writing: 0,
+  reports_to_review: 0,
+  latest_run: null,
 };
 
 export const source: SourceView = {
```

- [ ] **Step 7: Run the tests, lint and the gates**

Run: `make test-engine`
Expected: 964 passed (956 before), coverage at least 95%.

Run: `make test-api`
Expected: 173 passed (171 before), coverage at least 95%; `test_committed_openapi_matches_the_app` and `test_every_screen_has_its_routes` pass unchanged.

Run: `make lint && cd web && pnpm test`
Expected: clean; 322 Vitest passed.

- [ ] **Step 8: Commit**

```bash
cat > "$SCRATCH/m18-task3-commit.txt" <<'EOF'
feat: project summary for the sidebar, review decision on the run list, auth.logout_url (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add engine/corelata/schema/progress.py engine/corelata/schema/__init__.py engine/corelata/store/runs.py engine/corelata/service.py engine/corelata/config.py engine/corelata.example.yaml deploy/config/corelata.example.yaml engine/tests/store/test_project_summaries.py engine/tests/test_config.py api/corelata_api/routes/projects.py api/corelata_api/routes/system.py api/tests/test_projects.py api/tests/test_app.py schema/openapi.json schema/run-summary.schema.json web/src/api/schema.d.ts web/src/api/types.ts web/src/test/fixtures.ts
git -C "$REPO" commit -F "$SCRATCH/m18-task3-commit.txt"
```

---

### Task 4: The frame: header, project sidebar, Help, the word map and the statuses

**Files:**
- Create: `web/src/lib/words.ts`, `web/src/lib/words.test.ts`, `web/src/lib/status.test.ts`, `web/src/components/Sidebar.tsx`, `web/src/components/Sidebar.test.tsx`, `web/src/components/HelpDialog.tsx`, `web/src/components/HelpDialog.test.tsx`, `web/src/components/frame.ts`, `web/src/components/frame.test.tsx`
- Modify: `web/src/lib/status.ts`, `web/src/components/Layout.tsx`, `web/src/components/Layout.test.tsx`, `web/src/components/NotFound.tsx`, `web/src/components/primitives.test.tsx`, `web/src/api/projects.ts`, `web/src/api/runs.ts`, `web/src/api/events.ts`, `web/src/api/types.ts`, `web/src/pages/new/NewRunPage.tsx`, `web/src/pages/new/ProjectPicker.test.tsx`, `web/src/pages/run/RunPage.tsx`, `web/src/pages/review/ReviewPage.tsx`, `web/src/test/server.ts`, `web/src/test/poll.ts`

**Interfaces:**
- Consumes: Task 1's shell classes and `useTheme`; Task 2's `Dialog`, `StatusText`, `Status`, `groupByDate`, `keyBelongsToControl`; Task 3's `ProjectView` summary fields, `RunSummary.review_decision`/`review_child_state`, `SystemInfo.logout_url`.
- Produces: `lib/words.ts`: `STEP_LABEL: Record<RunState, string>`, `PROGRESS_STEPS` (the eight steps), `type ProgressStep`, `REVISED_STEPS`, `VERDICT: Record<Verdict, {symbol, text}>`, `SEVERITY`, `CLAIM_KIND`, `plural(n, one, many?)`, `citedByText(path)`, `degradationText(line) -> {text, detail}`, `reportStatusText(status, open)`; `lib/status.ts`: `type RunLike = {state, decision, childState}`, `fromProgress(run)`, `fromSummary(run)`, `runStatus(run)`, `projectStatus(project)`; `components/frame.ts`: `ActiveProjectContext`, `useActiveProject(projectId)`, `useDocumentTitle(title)`; `Sidebar({open, activeProject, onNavigate})`, `SEARCH_FROM = 15`; `HelpDialog({open, onClose})`; `api/projects.ts`: `PROJECTS_POLL_MS = 5000`, `refreshProjects(queryClient)`; `test/poll.ts`: `projectsRefetchInterval(queryClient)`; `ClaimKind` in `api/types.ts`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/words.test.ts`:

```ts
import { readFileSync } from "node:fs";
import {
  CLAIM_KIND,
  citedByText,
  degradationText,
  plural,
  PROGRESS_STEPS,
  reportStatusText,
  SEVERITY,
  STEP_LABEL,
  VERDICT,
} from "./words";

// The API's own list of every value it can send (tests run from web/): a value the engine adds
// later fails here before it reaches a screen as a bare engine word (M18 spec §4).
const schemas = (
  JSON.parse(readFileSync("../schema/openapi.json", "utf8")) as {
    components: { schemas: Record<string, { enum?: string[] }> };
  }
).components.schemas;
const values = (name: string) => schemas[name]!.enum!;

it.each([
  ["RunState", STEP_LABEL],
  ["Verdict", VERDICT],
  ["Severity", SEVERITY],
  ["ClaimKind", CLAIM_KIND],
] as const)("has a word for every %s the API can send", (name, words) => {
  expect(Object.keys(words).sort()).toEqual([...values(name)].sort());
});

it("lists the writing steps in the pipeline's order, from waiting to ready", () => {
  expect(PROGRESS_STEPS.map((s) => STEP_LABEL[s])).toEqual([
    "Waiting to start",
    "Reading the sources",
    "Checking the value statement",
    "Drafting",
    "Editing for the reader",
    "Checking against the standards",
    "Preparing the documents",
    "Ready to review",
  ]);
});

it("says where a claim is cited in the reader's words, and keeps an unknown path", () => {
  expect(citedByText("key_judgments[0]")).toBe("Key judgments, item 1");
  expect(citedByText("analysis[0].paragraphs[1]")).toBe("Analysis, section 1, paragraph 2");
  expect(citedByText("alternatives[2]")).toBe("Alternatives, item 3");
  expect(citedByText("appendix.x")).toBe("appendix.x");
});

it("words a degradation in both forms, keeps the engine's error, and keeps any other line", () => {
  expect(degradationText("conveyance skipped after 2 attempts: conveyor: bad JSON")).toEqual({
    text: "Editing for the reader was skipped after 2 attempts.",
    detail: "conveyor: bad JSON",
  });
  expect(degradationText("audit incomplete after 1 attempt: auditor: timeout")).toEqual({
    text: "The standards check didn't finish after 1 attempt.",
    detail: "auditor: timeout",
  });
  expect(degradationText("something new")).toEqual({ text: "something new", detail: null });
  expect(degradationText("audit incomplete")).toEqual({ text: "audit incomplete", detail: null });
});

it("words a report's status", () => {
  expect(reportStatusText("clean", 0)).toBe("Meets the standards");
  expect(reportStatusText("findings_open", 1)).toBe("1 standard not met");
  expect(reportStatusText("findings_open", 3)).toBe("3 standards not met");
  expect(reportStatusText("findings_open", 0)).toBe("Checked in part");
  expect(plural(2, "passage")).toBe("2 passages");
});
```

Create `web/src/lib/status.test.ts`:

```ts
import type { RunState } from "../api/types";
import { project, runProgress, runSummary } from "../test/fixtures";
import { fromProgress, fromSummary, projectStatus, runStatus, type RunLike } from "./status";

const run = (
  state: RunState,
  decision: RunLike["decision"] = null,
  childState: RunState | null = null,
) => runStatus({ state, decision, childState });
const shown = (s: { symbol: string; text: string; tone: string }) =>
  `${s.symbol} ${s.text} (${s.tone})`.trim();

it("gives every report state its words, symbol and tone (spec §4.2)", () => {
  expect(shown(run("created"))).toBe("… waiting to start (busy)");
  for (const state of ["ingesting", "gating", "drafting", "conveying", "auditing", "rendering"]) {
    expect(shown(run(state as RunState))).toBe("… writing (busy)");
  }
  expect(shown(run("completed"))).toBe("● to review (busy)");
  expect(shown(run("completed", "accepted"))).toBe("✓ accepted (ok)");
  expect(shown(run("completed", "returned"))).toBe("↺ returned (none)"); // revision being written
  expect(shown(run("completed", "returned", "completed"))).toBe("↺ returned (none)");
  for (const ended of ["failed", "cancelled", "gate_rejected"] as const) {
    // the revision ended without a report: to review again (R-M15-1)
    expect(shown(run("completed", "returned", ended))).toBe("● to review (busy)");
  }
  expect(shown(run("gate_rejected"))).toBe("⚠ not supported by the sources (warn)");
  expect(shown(run("failed"))).toBe("! couldn't finish (bad)");
  expect(shown(run("cancelled"))).toBe("■ stopped (none)");
});

it("reads a run's progress and a run list row the same way", () => {
  const review = {
    decision: "returned" as const,
    at: "2026-10-20T10:00:00Z",
    child_state: "failed" as const,
  };
  expect(fromProgress(runProgress({ state: "completed", review }))).toEqual({
    state: "completed",
    decision: "returned",
    childState: "failed",
  });
  expect(fromProgress(runProgress())).toEqual({
    state: "created",
    decision: null,
    childState: null,
  });
  expect(
    fromSummary({ ...runSummary, review_decision: "returned", review_child_state: "failed" }),
  ).toEqual({ state: "completed", decision: "returned", childState: "failed" });
  expect(fromSummary(runSummary)).toEqual({ state: "completed", decision: null, childState: null });
});

const latest = (state: RunState, decision: "accepted" | "returned" | null = null) => ({
  run_id: "r",
  state,
  status: null,
  decision,
});

it("gives a project the first status that holds (spec §3.3)", () => {
  const p = (overrides: Partial<typeof project>) =>
    shown(projectStatus({ ...project, ...overrides }));
  expect(p({ reports_writing: 1, reports_to_review: 2, latest_run: latest("failed") })).toBe(
    "… writing (busy)",
  );
  expect(p({ reports_to_review: 2, latest_run: latest("failed") })).toBe("● 2 to review (busy)");
  expect(p({ latest_run: latest("failed") })).toBe("! needs attention (bad)");
  expect(p({ latest_run: latest("gate_rejected") })).toBe("⚠ not supported (warn)");
  expect(p({ latest_run: latest("completed", "accepted") })).toBe("✓ accepted (ok)");
  expect(p({ latest_run: latest("cancelled") })).toBe("■ stopped (none)");
  expect(p({ latest_run: null })).toBe("no reports yet (none)");
  // anything else: the latest report's own status (R-M18-6)
  expect(p({ latest_run: latest("completed", "returned") })).toBe("↺ returned (none)");
});
```

Create `web/src/components/Sidebar.test.tsx`:

```tsx
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { PROJECTS_POLL_MS } from "../api/projects";
import type { ProjectView } from "../api/types";
import { noRuns, packs, project, RUN_ID, runProgress } from "../test/fixtures";
import { projectsRefetchInterval } from "../test/poll";
import { renderApp } from "../test/render";
import { server } from "../test/server";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

let made = 0;
function named(name: string, overrides: Partial<ProjectView> = {}): ProjectView {
  made += 1;
  return {
    ...project,
    id: `${String(made).padStart(8, "0")}-1111-1111-1111-111111111111`,
    name,
    ...overrides,
  };
}

function serve(list: ProjectView[]) {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json(list)),
    http.get("*/api/projects/:id/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.get("*/api/packs", () => HttpResponse.json(packs)),
  );
}

const sidebar = () => screen.getByRole("navigation", { name: "Your projects" });

it("groups the projects by their last activity, newest first, each with one status", async () => {
  serve([
    named("old", { last_activity_at: hoursAgo(24 * 30) }),
    named("week", { last_activity_at: hoursAgo(48), reports_to_review: 2 }),
    named("now", { last_activity_at: hoursAgo(0.1), reports_writing: 1 }),
    named("later", { last_activity_at: hoursAgo(0.2) }),
  ]);
  renderApp("/new");
  const today = await within(sidebar()).findByRole("region", { name: "Today" });
  expect(
    within(today)
      .getAllByRole("link")
      .map((a) => a.textContent),
  ).toEqual(["now… writing", "laterno reports yet"]);
  expect(within(sidebar()).getByRole("region", { name: "This week" })).toHaveTextContent(
    "week● 2 to review",
  );
  expect(within(sidebar()).getByRole("region", { name: "Earlier" })).toHaveTextContent("old");
  expect(within(sidebar()).getByRole("link", { name: /^now/ }).getAttribute("href")).toMatch(
    /^\/new\?project=\d{8}-/,
  );
  expect(within(sidebar()).getByRole("link", { name: "+ New report" })).toHaveAttribute(
    "href",
    "/new",
  );
});

it("says where the projects will appear, and searches from 16 projects on", async () => {
  serve([]);
  renderApp("/new");
  expect(await screen.findByText("Your projects will appear here.")).toBeInTheDocument();
  cleanup();
  const fifteen = Array.from({ length: 15 }, (_, i) => named(`p${i}`));
  serve(fifteen);
  renderApp("/new");
  await waitFor(() => expect(within(sidebar()).getAllByRole("listitem")).toHaveLength(15));
  expect(screen.queryByRole("searchbox", { name: "Search your projects" })).toBeNull();
  cleanup();
  serve([...fifteen, named("Danube")]);
  const { user } = renderApp("/new");
  await user.type(await screen.findByRole("searchbox", { name: "Search your projects" }), "DANU");
  expect(within(sidebar()).getAllByRole("listitem")).toHaveLength(1);
  expect(within(sidebar()).getByRole("link", { name: /^Danube/ })).toBeInTheDocument();
});

it("marks the project page's row and a run's project as the current page", async () => {
  const other = named("other");
  serve([project, other]);
  server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress())));
  const { router } = renderApp(`/new?project=${project.id}`);
  const row = await within(sidebar()).findByRole("link", { name: /^Black Sea/ });
  await waitFor(() => expect(row).toHaveAttribute("aria-current", "page"));
  expect(within(sidebar()).getByRole("link", { name: /^other/ })).not.toHaveAttribute(
    "aria-current",
  );
  await router.navigate(`/runs/${RUN_ID}`);
  await waitFor(() =>
    expect(within(sidebar()).getByRole("link", { name: /^Black Sea/ })).toHaveAttribute(
      "aria-current",
      "page",
    ),
  );
  await router.navigate("/new");
  await waitFor(() =>
    expect(within(sidebar()).getByRole("link", { name: /^Black Sea/ })).not.toHaveAttribute(
      "aria-current",
    ),
  );
});

it("reads the list again every 5 s while a report is being written, and not otherwise", async () => {
  let writing = 1;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([{ ...project, reports_writing: writing }])),
  );
  const { queryClient } = renderApp("/new");
  await within(sidebar()).findByText("writing");
  expect(projectsRefetchInterval(queryClient)).toBe(PROJECTS_POLL_MS);
  writing = 0;
  await queryClient.refetchQueries({ queryKey: ["projects"], exact: true });
  await within(sidebar()).findByText("no reports yet");
  expect(projectsRefetchInterval(queryClient)).toBe(false);
});

it("shows a project-list failure in the sidebar", async () => {
  server.use(
    http.get("*/api/projects", () =>
      HttpResponse.json({ detail: "database offline" }, { status: 400 }),
    ),
  );
  renderApp("/new");
  expect(await within(sidebar()).findByRole("alert")).toHaveTextContent("database offline");
});
```

Create `web/src/components/HelpDialog.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HelpDialog } from "./HelpDialog";

it("explains the keys, every status with its symbol, the steps and the standards results", async () => {
  const onClose = vi.fn();
  render(<HelpDialog open onClose={onClose} />);
  const help = screen.getByRole("dialog", { name: "Help" });
  expect(help).toHaveTextContent("Open this help");
  expect(help).toHaveTextContent("Move between the tabs of a review");
  expect(help).toHaveTextContent("Close a menu or a dialog");
  for (const status of [
    "… writing",
    "● to review",
    "✓ accepted",
    "↺ returned",
    "⚠ not supported by the sources",
    "! couldn't finish",
    "■ stopped",
  ]) {
    expect(help).toHaveTextContent(status);
  }
  const steps = within(help).getAllByRole("list")[1]!;
  expect(within(steps).getAllByRole("listitem")).toHaveLength(8);
  expect(steps).toHaveTextContent("Checking the value statement");
  for (const result of [
    "✓ met",
    "✗ not met",
    "– doesn't apply",
    "◇ attested",
    "Return with note",
  ]) {
    expect(help).toHaveTextContent(result);
  }
  await userEvent.setup().click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
});
```

Create `web/src/components/frame.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { ActiveProjectContext, useActiveProject, useDocumentTitle } from "./frame";

function Page({ project, title }: { project: string | null; title: string | null }) {
  useActiveProject(project);
  useDocumentTitle(title);
  return null;
}

it("names the page's project to the frame while it is on screen, and sets the tab's title", () => {
  const seen: (string | null)[] = [];
  const set = (id: string | null) => seen.push(id);
  document.title = "Corelata";
  const { rerender, unmount } = render(
    <ActiveProjectContext.Provider value={set}>
      <Page project="p1" title={null} />
    </ActiveProjectContext.Provider>,
  );
  expect(document.title).toBe("Corelata"); // null: still loading, left alone
  rerender(
    <ActiveProjectContext.Provider value={set}>
      <Page project="p2" title="Black Sea – Corelata" />
    </ActiveProjectContext.Provider>,
  );
  expect(document.title).toBe("Black Sea – Corelata");
  unmount();
  expect(seen).toEqual(["p1", null, "p2", null]);
});

it("does nothing outside a frame", () => {
  expect(() => render(<Page project="p1" title={null} />)).not.toThrow();
});
```

Replace `web/src/components/Layout.test.tsx` (the header, Sign out, `?`, the narrow toggle; the version is now the sidebar's foot):

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { makeQueryClient, Providers } from "../Providers";
import { routes } from "../routes";
import { info } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

it("shows the name, the theme toggle, Help and Settings, and no user or Sign out by default", async () => {
  renderApp("/new");
  const header = screen.getByRole("banner");
  expect(within(header).getByRole("link", { name: "Corelata" })).toHaveAttribute("href", "/new");
  expect(within(header).getByRole("button", { name: "Help" })).toBeInTheDocument();
  expect(within(header).getByRole("link", { name: "Settings" })).toHaveAttribute(
    "href",
    "/settings",
  );
  expect(within(header).getByRole("button", { name: /^Switch to the/ })).toBeInTheDocument();
  expect(await screen.findByText("Corelata 0.1.0")).toBeInTheDocument(); // the sidebar's foot
  expect(within(header).queryByRole("button", { name: "Sign out" })).toBeNull();
});

it("shows who is signed in and a Sign out form when the API reports them", async () => {
  server.use(
    http.get("*/api/system/info", () =>
      HttpResponse.json({
        ...info,
        user: "ana",
        auth_mode: "trusted_header",
        logout_url: "/oauth2/sign_out",
      }),
    ),
  );
  renderApp("/new");
  expect(await screen.findByText("ana")).toBeInTheDocument();
  const signOut = screen.getByRole("button", { name: "Sign out" });
  expect(signOut.closest("form")).toHaveAttribute("action", "/oauth2/sign_out");
  expect(signOut.closest("form")).toHaveAttribute("method", "post");
});

it("opens Help with the ? key outside a text field, and from the header", async () => {
  const { user } = renderApp("/new");
  fireEvent.keyDown(window, { key: "?" });
  expect(await screen.findByRole("dialog", { name: "Help" })).toHaveAttribute("open");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Help" }));
  expect(screen.getByRole("dialog", { name: "Help" })).toHaveAttribute("open");
});

it("leaves the ? key to a text field", async () => {
  renderApp("/new");
  const field = document.createElement("textarea");
  document.body.appendChild(field);
  fireEvent.keyDown(field, { key: "?" });
  expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  field.remove();
});

it("opens the sidebar from the header on a narrow screen", async () => {
  const { user } = renderApp("/new");
  const toggle = screen.getByRole("button", { name: "Your projects" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("navigation", { name: "Your projects" })).toHaveClass("open");
  await user.click(screen.getByRole("link", { name: "+ New report" }));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

it("redirects the root to the new report screen and shows the not-found page elsewhere", async () => {
  const { router } = renderApp("/");
  expect(router.state.location.pathname).toBe("/new");
  renderApp("/nope");
  expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
});

it("shows the info error inline when the API is unreachable", async () => {
  server.use(http.get("*/api/system/info", () => HttpResponse.error()));
  renderApp("/new");
  expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("could not be reached");
});

it("replaces a crashing page inside the layout", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const Boom = () => {
    throw new Error("page exploded");
  };
  const root = routes[0] as { children: { children: RouteObject[] }[] } & RouteObject;
  const page = root.children[0]!;
  const withBoom = [
    {
      ...root,
      children: [{ ...page, children: [...page.children, { path: "boom", element: <Boom /> }] }],
    },
  ] as RouteObject[];
  const router = createMemoryRouter(withBoom, { initialEntries: ["/boom"] });
  render(
    <Providers client={makeQueryClient({ retry: false })}>
      <RouterProvider router={router} />
    </Providers>,
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Corelata" })).toBeInTheDocument();
});

it("switches the theme from the header and names the theme it switches to", async () => {
  localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  const { user } = renderApp("/new");
  await user.click(await screen.findByRole("button", { name: "Switch to the dark theme" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("corelata.theme")).toBe("dark");
  await user.click(screen.getByRole("button", { name: "Switch to the light theme" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  localStorage.clear();
});
```

The not-found link's words, and the project list's failure now shows in the sidebar too:

```diff
diff --git a/web/src/components/primitives.test.tsx b/web/src/components/primitives.test.tsx
index 507488b..d2adebe 100644
--- a/web/src/components/primitives.test.tsx
+++ b/web/src/components/primitives.test.tsx
@@ -7,9 +7,9 @@ import { Loading } from "./Loading";
 import { RouteError } from "./RouteError";
 import { StateBadge } from "./StateBadge";
 
-it("links the not-found page back to the new-run screen", async () => {
+it("links the not-found page back to the new report screen", async () => {
   renderApp("/nope");
-  expect(await screen.findByRole("link", { name: "Start a new run" })).toHaveAttribute(
+  expect(await screen.findByRole("link", { name: "Start a new report" })).toHaveAttribute(
     "href",
     "/new",
   );
```

```diff
diff --git a/web/src/pages/new/ProjectPicker.test.tsx b/web/src/pages/new/ProjectPicker.test.tsx
index a8110f8..89a6255 100644
--- a/web/src/pages/new/ProjectPicker.test.tsx
+++ b/web/src/pages/new/ProjectPicker.test.tsx
@@ -1,4 +1,4 @@
-import { act, screen, waitFor } from "@testing-library/react";
+import { act, screen, waitFor, within } from "@testing-library/react";
 import { delay, http, HttpResponse } from "msw";
 import { noRuns, packs, project, source } from "../../test/fixtures";
 import { renderApp } from "../../test/render";
@@ -80,7 +80,10 @@ it("shows a project-list failure inline", async () => {
     ),
   );
   renderApp("/new");
-  expect(await screen.findByRole("alert")).toHaveTextContent("database offline");
+  // the sidebar shows it too (M18 spec §3.3)
+  expect(await within(screen.getByRole("main")).findByRole("alert")).toHaveTextContent(
+    "database offline",
+  );
 });
 
 it("shows no project field while the list is loading", async () => {
```

The harness: every page renders the sidebar (R-M18-16), and the project list's interval is read like the others:

```diff
diff --git a/web/src/test/server.ts b/web/src/test/server.ts
index 1e6d845..2206f0f 100644
--- a/web/src/test/server.ts
+++ b/web/src/test/server.ts
@@ -2,5 +2,9 @@ import { http, HttpResponse } from "msw";
 import { setupServer } from "msw/node";
 import { info } from "./fixtures";
 
-// Every page renders the layout, which asks who is signed in and which version answers.
-export const server = setupServer(http.get("*/api/system/info", () => HttpResponse.json(info)));
+// Every page renders the layout, which asks who is signed in and which version answers, and
+// the sidebar, which lists the projects (none, unless a test serves some).
+export const server = setupServer(
+  http.get("*/api/system/info", () => HttpResponse.json(info)),
+  http.get("*/api/projects", () => HttpResponse.json([])),
+);
```

```diff
diff --git a/web/src/test/poll.ts b/web/src/test/poll.ts
index 268f140..2a2c1e4 100644
--- a/web/src/test/poll.ts
+++ b/web/src/test/poll.ts
@@ -1,5 +1,6 @@
 import type { Query, QueryClient, QueryKey } from "@tanstack/react-query";
 import { discoveryKeys } from "../api/discoveries";
+import { projectKeys } from "../api/projects";
 import { runKeys } from "../api/runs";
 
 /** What the active observer of the query `queryKey` would use as its refetch interval now. */
@@ -14,6 +15,11 @@ export function runRefetchInterval(queryClient: QueryClient, runId: string): unk
   return refetchInterval(queryClient, runKeys.one(runId));
 }
 
+/** The same for the sidebar's project list (M18 spec §3.3). */
+export function projectsRefetchInterval(queryClient: QueryClient): unknown {
+  return refetchInterval(queryClient, projectKeys.all);
+}
+
 /** The same for a discovery's query (R-M16-2, R-M16-3). */
 export function discoveryRefetchInterval(queryClient: QueryClient, discoveryId: string): unknown {
   return refetchInterval(queryClient, discoveryKeys.one(discoveryId));
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/lib src/components`
Expected: FAIL: `Failed to resolve import "./words"`, `"./Sidebar"`, `"./HelpDialog"`, `"./frame"`; `status.test.ts` finds no `runStatus`; the Layout tests find no Help button, no "Your projects" navigation and no "Corelata 0.1.0" text.

- [ ] **Step 3: The word map and the statuses**

Create `web/src/lib/words.ts`:

```ts
import type { ClaimKind, ReportStatus, RunState, Severity, Verdict } from "../api/types";

/** The words the screens use for the engine's (M18 spec §4). The engine's own words stay in the
 * API, the CLI, the trace, the Process and Sources tabs and Settings ▸ Technical details (§4.4).
 * words.test.ts checks that every value the API can send has a word here. */

/** §4.3: a run's state as a step of writing the report. The last three are not steps but
 * outcomes; the Process tab names a stage with these words. */
export const STEP_LABEL: Record<RunState, string> = {
  created: "Waiting to start",
  ingesting: "Reading the sources",
  gating: "Checking the value statement",
  drafting: "Drafting",
  conveying: "Editing for the reader",
  auditing: "Checking against the standards",
  rendering: "Preparing the documents",
  completed: "Ready to review",
  gate_rejected: "Not supported by the sources",
  failed: "Couldn't finish",
  cancelled: "Stopped",
};

/** The steps the writing page lists, in order (§4.3, §5.3). */
export const PROGRESS_STEPS = [
  "created",
  "ingesting",
  "gating",
  "drafting",
  "conveying",
  "auditing",
  "rendering",
  "completed",
] as const satisfies readonly RunState[];
export type ProgressStep = (typeof PROGRESS_STEPS)[number];

/** Drafting, editing and checking repeat on a revision (§4.3). */
export const REVISED_STEPS: ReadonlySet<RunState> = new Set<RunState>([
  "drafting",
  "conveying",
  "auditing",
]);

/** §4.1: a rule's verdict, with its symbol. */
export const VERDICT: Record<Verdict, { symbol: string; text: string }> = {
  fail: { symbol: "✗", text: "not met" },
  pass: { symbol: "✓", text: "met" },
  not_applicable: { symbol: "–", text: "doesn't apply" },
  attested: { symbol: "◇", text: "attested" },
};

export const SEVERITY: Record<Severity, string> = {
  blocking: "Blocking",
  major: "Major",
  minor: "Minor",
};

export const CLAIM_KIND: Record<ClaimKind, string> = {
  fact: "Fact",
  judgment: "Judgment",
  assumption: "Assumption",
};

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "key_judgments[0]" → "Key judgments, item 1"; "analysis[0].paragraphs[1]" → "Analysis,
 * section 1, paragraph 2"; "alternatives[0]" → "Alternatives, item 1". Anything else as it is. */
export function citedByText(path: string): string {
  const item = /^(key_judgments|alternatives)\[(\d+)\]$/.exec(path);
  if (item) {
    const where = item[1] === "key_judgments" ? "Key judgments" : "Alternatives";
    return `${where}, item ${Number(item[2]) + 1}`;
  }
  const paragraph = /^analysis\[(\d+)\]\.paragraphs\[(\d+)\]$/.exec(path);
  if (paragraph) {
    return `Analysis, section ${Number(paragraph[1]) + 1}, paragraph ${Number(paragraph[2]) + 1}`;
  }
  return path;
}

/** §4.1: a stage the report was delivered without (`metadata.degradations`, R-M11-2), as a
 * sentence, with the engine's error kept for Details. A line in neither form stays as it is. */
export function degradationText(line: string): { text: string; detail: string | null } {
  const match =
    /^(conveyance skipped|audit incomplete) after (\d+) attempts?(?:: ([\s\S]*))?$/.exec(line);
  if (!match) return { text: line, detail: null };
  const attempts = plural(Number(match[2]), "attempt");
  const text =
    match[1] === "conveyance skipped"
      ? `Editing for the reader was skipped after ${attempts}.`
      : `The standards check didn't finish after ${attempts}.`;
  return { text, detail: match[3] ?? null };
}

/** §4.1: a delivered report's status in words: `clean`, or `findings_open` with the rules still
 * open, or `findings_open` only because a stage was skipped. */
export function reportStatusText(status: ReportStatus, open: number): string {
  if (status === "clean") return "Meets the standards";
  return open > 0 ? `${plural(open, "standard")} not met` : "Checked in part";
}
```

Replace `web/src/lib/status.ts`:

```ts
import type { ProjectView, ReviewDecision, RunProgress, RunState, RunSummary } from "../api/types";

/** Copied from Coglossa's lib/status.ts (spec §2.2): the tone classes are base.css's `tone-*`. */
export type Tone = "ok" | "warn" | "busy" | "bad" | "none";
/** A status always carries words, and a symbol where it has one; never colour alone. */
export type Status = { text: string; symbol: string; tone: Tone };

/** What `runStatus` reads: the run's state, its stored decision, and how the revision a return
 * made ended (null while it runs). */
export type RunLike = {
  state: RunState;
  decision: ReviewDecision | null;
  childState: RunState | null;
};

export function fromProgress(run: RunProgress): RunLike {
  return {
    state: run.state,
    decision: run.review?.decision ?? null,
    childState: run.review?.child_state ?? null,
  };
}

export function fromSummary(run: RunSummary): RunLike {
  return {
    state: run.state,
    decision: run.review_decision ?? null,
    childState: run.review_child_state ?? null,
  };
}

/** A revision that ended this way produced no report: the run is to review again (R-M15-1). */
const FREED_BY: ReadonlySet<RunState> = new Set<RunState>(["gate_rejected", "failed", "cancelled"]);

const WRITING: Status = { text: "writing", symbol: "…", tone: "busy" };
const TO_REVIEW: Status = { text: "to review", symbol: "●", tone: "busy" };

/** M18 spec §4.2: a report's status, for the sidebar, the project page and the writing page. */
export function runStatus(run: RunLike): Status {
  switch (run.state) {
    case "created":
      return { text: "waiting to start", symbol: "…", tone: "busy" };
    case "completed":
      if (run.decision === "accepted") return { text: "accepted", symbol: "✓", tone: "ok" };
      if (run.decision === "returned" && !(run.childState && FREED_BY.has(run.childState))) {
        return { text: "returned", symbol: "↺", tone: "none" };
      }
      return TO_REVIEW;
    case "gate_rejected":
      return { text: "not supported by the sources", symbol: "⚠", tone: "warn" };
    case "failed":
      return { text: "couldn't finish", symbol: "!", tone: "bad" };
    case "cancelled":
      return { text: "stopped", symbol: "■", tone: "none" };
    default:
      return WRITING;
  }
}

/** M18 spec §3.3: a project's one status in the sidebar, the first condition that holds. */
export function projectStatus(project: ProjectView): Status {
  if (project.reports_writing > 0) return WRITING;
  if (project.reports_to_review > 0) {
    return { ...TO_REVIEW, text: `${project.reports_to_review} to review` };
  }
  const latest = project.latest_run;
  if (latest === null) return { text: "no reports yet", symbol: "", tone: "none" };
  switch (latest.state) {
    case "failed":
      return { text: "needs attention", symbol: "!", tone: "bad" };
    case "gate_rejected":
      return { text: "not supported", symbol: "⚠", tone: "warn" };
    case "cancelled":
      return { text: "stopped", symbol: "■", tone: "none" };
    default:
      // accepted, or returned with its revision being written or written (R-M18-6)
      return runStatus({
        state: latest.state,
        decision: latest.decision ?? null,
        childState: null,
      });
  }
}
```

```diff
diff --git a/web/src/api/types.ts b/web/src/api/types.ts
index 30566b4..86aa5b0 100644
--- a/web/src/api/types.ts
+++ b/web/src/api/types.ts
@@ -40,6 +40,7 @@ export type Severity = S["Severity"];
 export type ClaimProvenance = S["ClaimProvenance"];
 export type EvidenceUnit = S["EvidenceUnit"];
 export type Claim = S["Claim"];
+export type ClaimKind = S["ClaimKind"];
 export type GateVerdict = S["GateVerdict"];
 export type ErrorBody = S["ErrorBody"];
```

- [ ] **Step 4: The frame**

Create `web/src/components/frame.ts`:

```ts
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
```

Create `web/src/components/Sidebar.tsx` (adapted from `$COGLOSSA/web/src/components/Sidebar.tsx`: projects, no row menu, the version at its foot):

```tsx
import { useState } from "react";
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
}: {
  open: boolean;
  activeProject: string | null;
  onNavigate: () => void;
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
    <nav aria-label="Your projects" className={open ? "sidebar open" : "sidebar"}>
      <Link to="/new" className="button primary new" onClick={onNavigate}>
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
                  onClick={onNavigate}
                >
                  <span className="project-name" dir="auto">
                    {p.name}
                  </span>
                  <StatusText status={projectStatus(p)} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <footer className="sidebar-foot muted">
        {info.data ? `Corelata ${info.data.version}` : ""}
      </footer>
    </nav>
  );
}
```

Create `web/src/components/HelpDialog.tsx` (Coglossa's shell, Corelata's content, spec §5.6):

```tsx
import { runStatus, type RunLike } from "../lib/status";
import { PROGRESS_STEPS, STEP_LABEL, VERDICT } from "../lib/words";
import { Dialog } from "./Dialog";

/** What each report status means (spec §4.2), as the screens show it. */
const STATUSES: [RunLike, string][] = [
  [
    { state: "drafting", decision: null, childState: null },
    "Corelata is still writing it. You can leave the page.",
  ],
  [
    { state: "completed", decision: null, childState: null },
    "Written and waiting for your review.",
  ],
  [
    { state: "completed", decision: "accepted", childState: null },
    "You or a colleague accepted it.",
  ],
  [
    { state: "completed", decision: "returned", childState: null },
    "Returned with a note; a revised report replaces it.",
  ],
  [
    { state: "gate_rejected", decision: null, childState: null },
    "The value check didn't find the statement in the sources.",
  ],
  [
    { state: "failed", decision: null, childState: null },
    "Something went wrong; the progress page says what.",
  ],
  [
    { state: "cancelled", decision: null, childState: null },
    "Stopped before the report was written.",
  ],
];

const STEP_HELP: Record<(typeof PROGRESS_STEPS)[number], string> = {
  created: "the report waits its turn.",
  ingesting: "the sources are split into passages.",
  gating: "the value statement is checked against the sources.",
  drafting: "the writer drafts the assessment.",
  conveying: "the draft is edited for its reader.",
  auditing: "every rule of the standards pack is checked.",
  rendering: "the documents you can download are made.",
  completed: "the report is ready for you.",
};

/** Adapted from Coglossa's HelpDialog (M18 spec §5.6): Corelata's keys, statuses, steps and
 * standards results on one short page. */
export function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} label="Help" onClose={onClose} className="dialog help">
      <h2>Help</h2>
      <h3>Keyboard</h3>
      <dl className="shortcuts">
        <dt>
          <kbd>?</kbd>
        </dt>
        <dd>Open this help</dd>
        <dt>
          <kbd>←</kbd> <kbd>→</kbd> <kbd>Home</kbd> <kbd>End</kbd>
        </dt>
        <dd>Move between the tabs of a review</dd>
        <dt>
          <kbd>Esc</kbd>
        </dt>
        <dd>Close a menu or a dialog</dd>
      </dl>
      <h3>What the statuses mean</h3>
      <ul>
        {STATUSES.map(([run, meaning]) => {
          const status = runStatus(run);
          return (
            <li key={status.text}>
              {status.symbol} {status.text}: {meaning}
            </li>
          );
        })}
      </ul>
      <h3>Writing a report</h3>
      <ol>
        {PROGRESS_STEPS.map((step) => (
          <li key={step}>
            {STEP_LABEL[step]}: {STEP_HELP[step]}
          </li>
        ))}
      </ol>
      <h3>The standards check</h3>
      <ul>
        <li>
          {VERDICT.pass.symbol} {VERDICT.pass.text} and {VERDICT.fail.symbol} {VERDICT.fail.text}:
          the report meets a rule of the standards pack, or does not.
        </li>
        <li>
          {VERDICT.not_applicable.symbol} {VERDICT.not_applicable.text}: the rule has nothing to
          check in this report.
        </li>
        <li>
          {VERDICT.attested.symbol} {VERDICT.attested.text}: an advisory rule a reader judges; the
          check records what it saw.
        </li>
        <li>
          Return with note: the note becomes guidance for a revised report, written from the same
          sources and statement.
        </li>
      </ul>
      <div className="row end">
        <button type="button" className="primary" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  );
}
```

Replace `web/src/components/Layout.tsx` (adapted from `$COGLOSSA/web/src/components/Layout.tsx`: `/api/system/info` instead of `/me`, the active project's context):

```tsx
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { useInfo } from "../api/system";
import { keyBelongsToControl } from "../lib/keys";
import { useTheme } from "../theme/theme";
import { ErrorMessage } from "./ErrorMessage";
import { ActiveProjectContext } from "./frame";
import { HelpDialog } from "./HelpDialog";
import { Sidebar } from "./Sidebar";

/** Adapted from Coglossa's Layout (M18 spec §3.1): the header, the project sidebar and the main
 * area. Who is signed in and the sign-out page come from GET /api/system/info (Corelata has no
 * /api/me). */
export function Layout() {
  const info = useInfo();
  const { theme, setChoice } = useTheme();
  const [help, setHelp] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const dark = theme === "dark";
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
            <form method="post" action={info.data.logout_url} className="signout">
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
          onNavigate={() => setNavOpen(false)}
        />
        <main className="main">
          <ActiveProjectContext.Provider value={setActiveProject}>
            <Outlet />
          </ActiveProjectContext.Provider>
        </main>
      </div>
      <HelpDialog open={help} onClose={() => setHelp(false)} />
    </div>
  );
}
```

```diff
diff --git a/web/src/components/NotFound.tsx b/web/src/components/NotFound.tsx
index 2fdc959..f516964 100644
--- a/web/src/components/NotFound.tsx
+++ b/web/src/components/NotFound.tsx
@@ -5,7 +5,7 @@ export function NotFound() {
     <section aria-label="Not found">
       <h1>Page not found</h1>
       <p>
-        <Link to="/new">Start a new run</Link>
+        <Link to="/new">Start a new report</Link>
       </p>
     </section>
   );
```

The pages name their project (R-M18-19):

```diff
diff --git a/web/src/pages/new/NewRunPage.tsx b/web/src/pages/new/NewRunPage.tsx
index d75e845..f10b85f 100644
--- a/web/src/pages/new/NewRunPage.tsx
+++ b/web/src/pages/new/NewRunPage.tsx
@@ -2,6 +2,7 @@ import { useCallback, useMemo, useState } from "react";
 import { useNavigate, useSearchParams } from "react-router";
 import { useStartRun } from "../../api/runs";
 import { ErrorMessage } from "../../components/ErrorMessage";
+import { useActiveProject } from "../../components/frame";
 import { RunOptions } from "./RunOptions";
 import { ValueStatement } from "./ValueStatement";
 import type { SourceView } from "../../api/types";
@@ -18,6 +19,7 @@ export const SOURCES_PARAM = "sources";
 export function NewRunPage() {
   const [params, setParams] = useSearchParams();
   const projectId = params.get("project");
+  useActiveProject(projectId);
   const sources = useSources(projectId);
   // Without the parameter every source is selected, new ones too. Ids that are not the
   // project's (removed, or a link from another project) are dropped without a word.
```

```diff
diff --git a/web/src/pages/run/RunPage.tsx b/web/src/pages/run/RunPage.tsx
index afe7a31..dc0da5a 100644
--- a/web/src/pages/run/RunPage.tsx
+++ b/web/src/pages/run/RunPage.tsx
@@ -3,6 +3,7 @@ import { Link, useParams } from "react-router";
 import { liveUpdatesAvailable, useRunEvents } from "../../api/events";
 import { useRun } from "../../api/runs";
 import { ErrorMessage } from "../../components/ErrorMessage";
+import { useActiveProject } from "../../components/frame";
 import { Loading } from "../../components/Loading";
 import { StateBadge } from "../../components/StateBadge";
 import { isTerminal } from "../../lib/format";
@@ -19,6 +20,7 @@ export function RunPage() {
   const live = liveUpdatesAvailable() && !streamFailed;
   const run = useRun(runId, live);
   const progress = run.data;
+  useActiveProject(progress?.project_id ?? null);
   const onStreamFailed = useCallback(() => setFailedRun(runId), [runId]);
   useRunEvents(
     runId,
```

```diff
diff --git a/web/src/pages/review/ReviewPage.tsx b/web/src/pages/review/ReviewPage.tsx
index 3ae0ad3..1c9c7ae 100644
--- a/web/src/pages/review/ReviewPage.tsx
+++ b/web/src/pages/review/ReviewPage.tsx
@@ -2,6 +2,7 @@ import { Link, useParams, useSearchParams } from "react-router";
 import { useReportHtml, useReportJson } from "../../api/reports";
 import { useRun } from "../../api/runs";
 import { ErrorMessage } from "../../components/ErrorMessage";
+import { useActiveProject } from "../../components/frame";
 import { Loading } from "../../components/Loading";
 import { Tabs } from "../../components/Tabs";
 import { AuditTab } from "./AuditTab";
@@ -25,6 +26,7 @@ export function ReviewPage() {
   const claim = params.get("claim");
   const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "provenance";
   const run = useRun(runId);
+  useActiveProject(run.data?.project_id ?? null);
   const completed = run.data?.state === "completed";
   const html = useReportHtml(runId, completed);
   const json = useReportJson(runId, completed);
```

- [ ] **Step 5: The sidebar's freshness (spec §3.3)**

The list is read again when the window regains focus, after a change that adds a project, a source, a report or a decision, when a run's stream reports its end, and every 5 s while a report is being written. Every invalidation is `exact`, so a project's sources and runs are not read again with it:

```diff
diff --git a/web/src/api/projects.ts b/web/src/api/projects.ts
index 02ef46a..e22d80e 100644
--- a/web/src/api/projects.ts
+++ b/web/src/api/projects.ts
@@ -1,4 +1,10 @@
-import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
+import {
+  type QueryClient,
+  useInfiniteQuery,
+  useMutation,
+  useQuery,
+  useQueryClient,
+} from "@tanstack/react-query";
 import { client, unwrap } from "./client";
 import type { ProjectView, RunPage, SourceKind, SourceView } from "./types";
 
@@ -9,13 +15,28 @@ export const projectKeys = {
   runs: (id: string) => ["projects", id, "runs"] as const,
 };
 
+/** How often the project list is read again while a report is being written (M18 spec §3.3). */
+export const PROJECTS_POLL_MS = 5000;
+
+/** Every project with its summary: the sidebar's list (M18 spec §3.3). Read again when the window
+ * regains focus, after a change that adds a project, a source, a report or a decision
+ * (`refreshProjects`), when a run's stream reports its end, and every 5 s while any report is
+ * being written; nothing else polls it. */
 export function useProjects() {
   return useQuery({
     queryKey: projectKeys.all,
     queryFn: ({ signal }) => unwrap<ProjectView[]>(client.GET("/api/projects", { signal })),
+    refetchOnWindowFocus: true,
+    refetchInterval: (query) =>
+      query.state.data?.some((p) => p.reports_writing > 0) ? PROJECTS_POLL_MS : false,
   });
 }
 
+/** The project list only, not each project's sources or runs (those keys start the same). */
+export function refreshProjects(queryClient: QueryClient): Promise<void> {
+  return queryClient.invalidateQueries({ queryKey: projectKeys.all, exact: true });
+}
+
 export function useProject(projectId: string | null) {
   return useQuery({
     queryKey: projectKeys.one(projectId ?? ""),
@@ -35,7 +56,7 @@ export function useCreateProject() {
   return useMutation({
     mutationFn: (name: string) =>
       unwrap<ProjectView>(client.POST("/api/projects", { body: { name } })),
-    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.all, exact: true }),
+    onSuccess: () => refreshProjects(queryClient),
   });
 }
 
@@ -76,7 +97,10 @@ export function useUploadSource(projectId: string) {
           },
         }),
       ),
-    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.sources(projectId) }),
+    onSuccess: () => {
+      void refreshProjects(queryClient);
+      return queryClient.invalidateQueries({ queryKey: projectKeys.sources(projectId) });
+    },
   });
 }
 
@@ -90,7 +114,10 @@ export function useFromCoglossa(projectId: string) {
           body: { run_id: runId },
         }),
       ),
-    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.sources(projectId) }),
+    onSuccess: () => {
+      void refreshProjects(queryClient);
+      return queryClient.invalidateQueries({ queryKey: projectKeys.sources(projectId) });
+    },
   });
 }
```

```diff
diff --git a/web/src/api/runs.ts b/web/src/api/runs.ts
index ff270ed..86acc3d 100644
--- a/web/src/api/runs.ts
+++ b/web/src/api/runs.ts
@@ -1,7 +1,7 @@
 import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
 import { isTerminal } from "../lib/format";
 import { ApiError, client, unwrap } from "./client";
-import { projectKeys } from "./projects";
+import { projectKeys, refreshProjects } from "./projects";
 import type {
   CreateRun,
   ReviewAction,
@@ -68,6 +68,7 @@ export function useStartRun() {
     onSuccess: (run) => {
       queryClient.setQueryData(runKeys.one(run.run_id), run);
       void queryClient.invalidateQueries({ queryKey: projectKeys.runs(run.project_id) });
+      void refreshProjects(queryClient);
     },
   });
 }
@@ -82,6 +83,7 @@ export function useCancelRun(runId: string) {
     onSuccess: (run) => {
       queryClient.setQueryData(runKeys.one(runId), run);
       void queryClient.invalidateQueries({ queryKey: projectKeys.runs(run.project_id) });
+      void refreshProjects(queryClient);
     },
   });
 }
@@ -105,6 +107,7 @@ export function useReview(runId: string) {
         queryClient.setQueryData(runKeys.one(result.child.run_id), result.child);
         void queryClient.invalidateQueries({ queryKey: projectKeys.runs(result.child.project_id) });
       }
+      void refreshProjects(queryClient); // the sidebar's "to review" count moved
       return refetched;
     },
     onError: (error) => {
```

```diff
diff --git a/web/src/api/events.ts b/web/src/api/events.ts
index 44ff386..39e38a3 100644
--- a/web/src/api/events.ts
+++ b/web/src/api/events.ts
@@ -2,6 +2,7 @@ import { useQueryClient } from "@tanstack/react-query";
 import { useEffect } from "react";
 import { isTerminal } from "../lib/format";
 import { eventsUrl } from "./client";
+import { refreshProjects } from "./projects";
 import { runKeys } from "./runs";
 import type { RunProgress } from "./types";
 
@@ -43,7 +44,10 @@ export function useRunEvents(runId: string, active: boolean, onStreamFailed?: ()
     source.addEventListener("progress", (event) => {
       const progress = JSON.parse(event.data) as RunProgress;
       queryClient.setQueryData<RunProgress>(runKeys.one(runId), progress);
-      if (isTerminal(progress.state)) source.close();
+      if (isTerminal(progress.state)) {
+        source.close();
+        void refreshProjects(queryClient); // the sidebar's row stops "writing" (M18 spec §3.3)
+      }
     });
     source.addEventListener("deleted", () => {
       source.close();
```

- [ ] **Step 6: Run the tests, lint and build**

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: clean; 345 passed in 49 files, coverage at least 95%. The pinned tests of `RunPage.test.tsx` ("ends on a deleted event…" still sees `invalidateQueries({queryKey: ["runs", RUN_ID], exact: true})`) and `ReviewActions.test.tsx` pass unchanged.

- [ ] **Step 7: Commit**

```bash
cat > "$SCRATCH/m18-task4-commit.txt" <<'EOF'
feat(web): header, project sidebar, Help, the word map and report statuses (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/src/lib/words.ts web/src/lib/words.test.ts web/src/lib/status.ts web/src/lib/status.test.ts web/src/components/Sidebar.tsx web/src/components/Sidebar.test.tsx web/src/components/HelpDialog.tsx web/src/components/HelpDialog.test.tsx web/src/components/frame.ts web/src/components/frame.test.tsx web/src/components/Layout.tsx web/src/components/Layout.test.tsx web/src/components/NotFound.tsx web/src/components/primitives.test.tsx web/src/api/projects.ts web/src/api/runs.ts web/src/api/events.ts web/src/api/types.ts web/src/pages/new/NewRunPage.tsx web/src/pages/new/ProjectPicker.test.tsx web/src/pages/run/RunPage.tsx web/src/pages/review/ReviewPage.tsx web/src/test/server.ts web/src/test/poll.ts
git -C "$REPO" commit -F "$SCRATCH/m18-task4-commit.txt"
```

---

### Task 5: New report and the project page (spec §5.1, §5.2)

**Files:**
- Create: `web/src/pages/new/AddSources.tsx`, `web/src/pages/new/AddSources.test.tsx`, `web/src/test/engine-words.ts`
- Delete: `web/src/pages/new/UploadSource.tsx`
- Modify: `web/src/pages/new/NewRunPage.tsx`, `ProjectPicker.tsx`, `SourcesPanel.tsx`, `ValueStatement.tsx`, `Suggestions.tsx`, `RunOptions.tsx`, `RunList.tsx`, `FetchFromCoglossa.tsx` and their tests `NewRunPage.test.tsx`, `ProjectPicker.test.tsx`, `SourcesPanel.test.tsx`, `ValueStatement.test.tsx`, `Suggestions.test.tsx`, `RunOptions.test.tsx`, `RunList.test.tsx`; `web/src/styles/new.css`

**Interfaces:**
- Consumes: Task 4's `useActiveProject`, `useDocumentTitle`, `runStatus`, `fromSummary`, `plural`, the sidebar ("Your projects" navigation, project links); Task 2's `StatusText`, `whenText`; Task 1's `.card`, `.primary`.
- Produces: `AddSources({projectId, maxUploadMb, onAdded})`, `ACCEPTED`, `sizeText(bytes)`, `fileProblem(file, maxMb)`, `uploadErrorText(error)`; `kindText(source)` in `SourcesPanel.tsx`; `test/engine-words.ts`: `ENGINE_WORDS`, `screenWords(root)`, `expectNoEngineWords(root)`; names on screen: "New report", "Which project is it for?", "Project" (eyebrow), "Use <name> in this report", "Choose files", "Chosen files", "Add as", "Upload", "Try again", "Suggestions" (live region), "More options", "Team profile", "Revision rounds", "Write the report", "Reports" (list).

- [ ] **Step 1: Write the failing tests**

Create `web/src/test/engine-words.ts` (R-M18-14):

```ts
/** The engine's words that must not reach the main flow (M18 spec §4, success criterion 4).
 * "run" stays allowed in "Coglossa run <id>" (a Coglossa run is Coglossa's word, §5.2). */
export const ENGINE_WORDS =
  /(?<!Coglossa |Coglossa run )\b(runs?|reruns?|discovery|discoveries|gate|gating|audit(s|ing)?|conveyor|conveying|conveyed|ingesting|iterations?|verdicts?|evidence units?|findings?|digested|pack)\b/i;

/** The page's visible words: its text, its buttons' and fields' names, and its live regions'
 * labels, so a reworded heading cannot hide an engine word in an aria-label. */
export function screenWords(root: HTMLElement): string {
  const labels = [...root.querySelectorAll("[aria-label]")].map((el) =>
    el.getAttribute("aria-label"),
  );
  return [root.textContent ?? "", ...labels].join(" \n ");
}

export function expectNoEngineWords(root: HTMLElement): void {
  expect(screenWords(root)).not.toMatch(ENGINE_WORDS);
}
```

Create `web/src/pages/new/AddSources.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { ApiError, errorText } from "../../api/client";
import { project, source } from "../../test/fixtures";
import { nodeFormData, NodeFileClass } from "../../test/node-web";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { AddSources, fileProblem, sizeText, uploadErrorText } from "./AddSources";

const MB = 1024 * 1024;
const file = (name: string, bytes = 10) => new File(["x".repeat(bytes)], name);

beforeEach(async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
});

function serveUploads(fail: Record<string, Response> = {}) {
  const order: { name: string; kind: string }[] = [];
  server.use(
    http.post(`*/api/projects/${project.id}/sources`, async ({ request }) => {
      const form = await request.formData();
      const name = (form.get("file") as File).name;
      order.push({ name, kind: String(form.get("kind")) });
      if (fail[name]) return fail[name]!.clone();
      return HttpResponse.json([{ ...source, id: `id-${name}`, name }], { status: 201 });
    }),
  );
  return order;
}

const chips = () => within(screen.getByRole("list", { name: "Chosen files" }));

it("takes several files by drop, uploads them in order, one request each, and hands each one on", async () => {
  const order = serveUploads();
  const added = vi.fn();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={added} />,
  );
  fireEvent.drop(screen.getByText("Drop files here, or click to choose").closest("label")!, {
    dataTransfer: { files: [file("a.txt"), file("b.pdf", 2 * MB)] },
  });
  expect(
    chips()
      .getAllByRole("listitem")
      .map((li) => li.textContent),
  ).toEqual(["a.txt 1 KB×", "b.pdf 2 MB×"]);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(added).toHaveBeenCalledTimes(2));
  expect(order).toEqual([
    { name: "a.txt", kind: "file" },
    { name: "b.pdf", kind: "file" },
  ]);
  expect(added.mock.calls.map(([list]) => list[0].name)).toEqual(["a.txt", "b.pdf"]);
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
});

it("marks a file over the limit and one of another type at once, and sends neither", async () => {
  const order = serveUploads();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={() => {}} />,
  );
  // dropped, so the file input's accept list does not filter them first
  fireEvent.drop(screen.getByText("Drop files here, or click to choose").closest("label")!, {
    dataTransfer: { files: [file("notes.pdf", 6 * MB), file("photo.png"), file("ok.md")] },
  });
  const alerts = chips().getAllByRole("alert");
  expect(alerts[0]).toHaveTextContent("notes.pdf is 6 MB, and the limit is 4 MB.");
  expect(alerts[1]).toHaveTextContent("photo.png isn't a file type Corelata reads");
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(order.map((o) => o.name)).toEqual(["ok.md"]));
  expect(chips().getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled(); // nothing left to send
  await user.click(screen.getByRole("button", { name: "Remove notes.pdf" }));
  expect(chips().getAllByRole("listitem")).toHaveLength(1);
});

it("keeps a failed file's chip with the reason and Try again while the next one carries on", async () => {
  const order = serveUploads({
    "a.txt": new Response("<html>413</html>", { status: 413 }),
  });
  const added = vi.fn();
  const { user } = renderWithClient(
    <AddSources projectId={project.id} maxUploadMb={4} onAdded={added} />,
  );
  await user.selectOptions(screen.getByRole("combobox", { name: "Add as" }), "coglossa_export");
  await user.upload(screen.getByLabelText("Choose files"), [file("a.txt"), file("b.json")]);
  await user.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(added).toHaveBeenCalledTimes(1));
  expect(order).toEqual([
    { name: "a.txt", kind: "coglossa_export" },
    { name: "b.json", kind: "coglossa_export" },
  ]);
  expect(chips().getByRole("alert")).toHaveTextContent("a.txt: too large for this server");
  serveUploads(); // the proxy's limit was raised
  await user.click(chips().getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(added).toHaveBeenCalledTimes(2));
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
});

it("words sizes and problems as Coglossa does", () => {
  expect(sizeText(10)).toBe("1 KB");
  expect(sizeText(1.5 * MB)).toBe("1.5 MB");
  expect(fileProblem(file("a.TXT"), 1)).toBeNull();
  expect(fileProblem(file("README"), 1)).toMatch(/isn't a file type Corelata reads/);
  expect(uploadErrorText(new ApiError(413, "big.txt is larger than the 1 MB upload limit"))).toBe(
    "big.txt is larger than the 1 MB upload limit",
  );
  expect(uploadErrorText(new ApiError(413, errorText(413, null)))).toBe(
    "too large for this server",
  );
  expect(uploadErrorText(new ApiError(422, "x.txt is empty"))).toBe("x.txt is empty");
});

it("shows the drop target while a file is dragged over it", () => {
  renderWithClient(<AddSources projectId={project.id} maxUploadMb={4} onAdded={() => {}} />);
  const area = screen.getByText("Drop files here, or click to choose").closest("label")!;
  fireEvent.dragOver(area);
  expect(area).toHaveClass("over");
  fireEvent.dragLeave(area);
  expect(area).not.toHaveClass("over");
  fireEvent.drop(area, { dataTransfer: { files: [] } });
  expect(chips().queryAllByRole("listitem")).toHaveLength(0);
});
```

The page's tests: the words, switching projects through the sidebar (Review Focus 5), and the new screens (§5.1, §5.2):

```diff
diff --git a/web/src/pages/new/NewRunPage.test.tsx b/web/src/pages/new/NewRunPage.test.tsx
index 2ba14f1..2f4bbda 100644
--- a/web/src/pages/new/NewRunPage.test.tsx
+++ b/web/src/pages/new/NewRunPage.test.tsx
@@ -1,4 +1,4 @@
-import { cleanup, screen, waitFor } from "@testing-library/react";
+import { cleanup, screen, waitFor, within } from "@testing-library/react";
 import { http, HttpResponse } from "msw";
 import type { SourceView } from "../../api/types";
 import { deferred } from "../../test/deferred";
@@ -11,11 +11,15 @@ import {
   packs,
   project,
   runProgress,
+  runSummary,
   sources,
 } from "../../test/fixtures";
+import { expectNoEngineWords } from "../../test/engine-words";
 import { renderApp } from "../../test/render";
 import { server } from "../../test/server";
 
+const inSidebar = () => within(screen.getByRole("navigation", { name: "Your projects" }));
+
 function serve() {
   server.use(
     http.get("*/api/projects", () => HttpResponse.json([project])),
@@ -37,18 +41,20 @@ it("starts a run with the chosen sources, statement, profile and iterations, the
     http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
   );
   const { router, user } = renderApp(`/new?project=${project.id}`);
-  const start = await screen.findByRole("button", { name: "Start" });
+  const start = await screen.findByRole("button", { name: "Write the report" });
   expect(start).toBeDisabled(); // no statement yet
   await user.type(
     screen.getByRole("textbox", { name: "Value statement" }),
     "Varna matters to shippers",
   );
-  await user.click(screen.getByRole("checkbox", { name: "Use letter.coglossa.json in this run" }));
-  const profile = screen.getByRole("combobox", { name: "Profile" });
+  await user.click(
+    screen.getByRole("checkbox", { name: "Use letter.coglossa.json in this report" }),
+  );
+  const profile = screen.getByRole("combobox", { name: "Team profile" });
   expect(screen.getByRole("option", { name: "draft-west (draft)" })).toBeDisabled();
   await user.selectOptions(profile, "team-east");
-  await user.clear(screen.getByRole("spinbutton", { name: "Audit iterations" }));
-  await user.type(screen.getByRole("spinbutton", { name: "Audit iterations" }), "1");
+  await user.clear(screen.getByRole("spinbutton", { name: "Revision rounds" }));
+  await user.type(screen.getByRole("spinbutton", { name: "Revision rounds" }), "1");
   await user.click(start);
   await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
   expect(body).toEqual({
@@ -76,13 +82,11 @@ it("labels the deployment's default profile, sends profile null when left, and s
     }),
   );
   const { user } = renderApp(`/new?project=${project.id}`);
-  const profile = await screen.findByRole("combobox", { name: "Profile" });
-  expect(await screen.findByRole("option", { name: "Default profile (team-east)" })).toHaveValue(
-    "",
-  );
+  const profile = await screen.findByRole("combobox", { name: "Team profile" });
+  expect(await screen.findByRole("option", { name: "Default (team-east)" })).toHaveValue("");
   expect(profile).toHaveValue("");
   await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
-  await user.click(screen.getByRole("button", { name: "Start" }));
+  await user.click(screen.getByRole("button", { name: "Write the report" }));
   expect(await screen.findByRole("alert")).toHaveTextContent("is a draft");
 });
 
@@ -90,10 +94,10 @@ it("cannot start without a selected source", async () => {
   serve();
   const { user } = renderApp(`/new?project=${project.id}`);
   await user.type(await screen.findByRole("textbox", { name: "Value statement" }), "x");
-  for (const name of ["Use port.txt in this run", "Use letter.coglossa.json in this run"]) {
+  for (const name of ["Use port.txt in this report", "Use letter.coglossa.json in this report"]) {
     await user.click(screen.getByRole("checkbox", { name }));
   }
-  expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
+  expect(screen.getByRole("button", { name: "Write the report" })).toBeDisabled();
   expect(screen.getByText("Choose at least one source.")).toBeInTheDocument();
 });
 
@@ -125,7 +129,7 @@ it("keeps the chosen sources in the URL, so a reload selects them again (R-M17-6
     ),
   );
   const first = renderApp(`/new?project=${project.id}`);
-  const letter = await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this run` });
+  const letter = await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this report` });
   expect(letter).toBeChecked(); // no parameter: every source
   expect(chosenIn(first.router.state.location.search)).toBeNull();
   await first.user.click(letter);
@@ -144,10 +148,10 @@ it("keeps the chosen sources in the URL, so a reload selects them again (R-M17-6
 
   renderApp(url);
   expect(
-    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this run` }),
+    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
   ).toBeChecked();
   expect(
-    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this run` }),
+    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
   ).not.toBeChecked();
   expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
     "1 of 2 selected",
@@ -169,16 +173,16 @@ it("drops ids in the URL that are not the project's, and starts with the rest",
   );
   const { router, user } = renderApp(`/new?project=${project.id}&sources=${GONE},${PORT.id}`);
   expect(
-    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this run` }),
+    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
   ).toBeChecked();
   expect(
-    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this run` }),
+    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this report` }),
   ).not.toBeChecked();
   expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
     "1 of 2 selected",
   );
   await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
-  await user.click(screen.getByRole("button", { name: "Start" }));
+  await user.click(screen.getByRole("button", { name: "Write the report" }));
   await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
   expect(body.source_ids).toEqual([PORT.id]); // the stale id is not sent
 });
@@ -187,9 +191,9 @@ it("a URL that names none of the project's sources selects none", async () => {
   serve();
   renderApp(`/new?project=${project.id}&sources=${GONE}`);
   expect(
-    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this run` }),
+    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this report` }),
   ).not.toBeChecked();
-  expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
+  expect(screen.getByRole("button", { name: "Write the report" })).toBeDisabled();
   expect(screen.getByText("Choose at least one source.")).toBeInTheDocument();
 });
 
@@ -204,7 +208,7 @@ it("choosing another project drops the discovery and the chosen sources from the
     `/new?project=${project.id}&sources=${PORT.id}&discovery=${DISCOVERY_ID}`,
   );
   await screen.findByRole("list", { name: "Suggested value statements" });
-  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), OTHER.id);
+  await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
   await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
   expect(
     screen.queryByRole("list", { name: "Suggested value statements" }),
@@ -227,7 +231,7 @@ it("a discovery that starts for the old project does not write itself into the n
   const { router, user, queryClient } = renderApp(`/new?project=${project.id}`);
   await user.click(await screen.findByRole("button", { name: "Suggest value" }));
   await waitFor(() => expect(posted).toBe(true));
-  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), OTHER.id);
+  await user.click(inSidebar().getByRole("link", { name: /^Baltic/ }));
   await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
   held.resolve();
   // the answer arrived and the mutation settled: whatever it would write, it has written
@@ -235,3 +239,58 @@ it("a discovery that starts for the old project does not write itself into the n
   await waitFor(() => expect(queryClient.isMutating()).toBe(0));
   expect(router.state.location.search).toBe(`?project=${OTHER.id}`);
 });
+
+it("New report without a project asks which project, and names the tab (M18 spec §5.1, §3.4)", async () => {
+  serve();
+  renderApp("/new");
+  expect(await screen.findByRole("heading", { name: "New report" })).toBeInTheDocument();
+  expect(screen.getByRole("heading", { name: "Which project is it for?" })).toBeInTheDocument();
+  expect(await screen.findByRole("combobox", { name: "Project" })).toHaveValue("");
+  expect(document.title).toBe("New report – Corelata");
+  expect(screen.queryByRole("region", { name: "Sources" })).toBeNull();
+});
+
+it("the project page names the project, has no picker, folds the options and has one primary button", async () => {
+  serve();
+  renderApp(`/new?project=${project.id}`);
+  const main = screen.getByRole("main");
+  expect(await within(main).findByRole("heading", { name: project.name })).toBeInTheDocument();
+  expect(within(main).getByText("Project")).toHaveClass("eyebrow");
+  expect(within(main).queryByRole("combobox", { name: "Project" })).toBeNull();
+  await waitFor(() => expect(document.title).toBe(`${project.name} – Corelata`));
+  const options = within(main).getByText("More options").closest("details")!;
+  expect(options).not.toHaveAttribute("open");
+  expect(within(options).getByRole("combobox", { name: "Team profile" })).toBeInTheDocument();
+  expect(within(options).getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(2);
+  expect(main.querySelectorAll("button.primary")).toHaveLength(1);
+  expect(within(main).getByRole("button", { name: "Write the report" })).toHaveClass("primary");
+});
+
+it("shows no engine word on the project page, with sources, suggestions and reports (M18 spec §4)", async () => {
+  serve();
+  server.use(
+    http.get("*/api/runs", () =>
+      HttpResponse.json({
+        runs: [
+          { ...runSummary, run_id: "a0000000-0000-0000-0000-000000000000", state: "drafting" },
+          { ...runSummary, review_decision: "returned", review_child_state: "failed" },
+        ],
+        next_before: null,
+      }),
+    ),
+    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
+      HttpResponse.json(
+        discoveryView({
+          state: "completed",
+          candidates: [{ ...candidates[0]!, confidence_note: "Stated directly." }],
+        }),
+      ),
+    ),
+  );
+  renderApp(`/new?project=${project.id}&discovery=${DISCOVERY_ID}`);
+  const main = screen.getByRole("main");
+  await within(main).findByRole("list", { name: "Suggested value statements" });
+  await within(main).findByRole("list", { name: "Reports" });
+  expect(within(main).getByText(/· 2 passages$/)).toBeInTheDocument();
+  expectNoEngineWords(main);
+});
```

```diff
diff --git a/web/src/pages/new/ProjectPicker.test.tsx b/web/src/pages/new/ProjectPicker.test.tsx
index 89a6255..581f19f 100644
--- a/web/src/pages/new/ProjectPicker.test.tsx
+++ b/web/src/pages/new/ProjectPicker.test.tsx
@@ -26,11 +26,13 @@ it("lists projects, selects one into the URL and creates a new one", async () =>
   expect(picker).toHaveValue("");
   await user.selectOptions(picker, project.id);
   expect(router.state.location.search).toBe(`?project=${project.id}`);
-  await user.click(screen.getByRole("button", { name: "New project" }));
+  expect(await screen.findByRole("heading", { name: project.name })).toBeInTheDocument();
+  await user.click(screen.getByRole("link", { name: "+ New report" }));
+  await user.click(await screen.findByRole("button", { name: "New project" }));
   await user.type(screen.getByRole("textbox", { name: "Project name" }), "Baltic");
   await user.click(screen.getByRole("button", { name: "Create" }));
   await waitFor(() => expect(router.state.location.search).toBe(`?project=${other.id}`));
-  expect(await screen.findByRole("combobox", { name: "Project" })).toHaveValue(other.id);
+  expect(await screen.findByRole("heading", { name: "Baltic" })).toBeInTheDocument();
 });
 
 it("shows a duplicate-name conflict inline", async () => {
@@ -54,17 +56,13 @@ it("keeps the project from the URL on reload", async () => {
     http.get("*/api/runs", () => HttpResponse.json(noRuns)),
   );
   renderApp(`/new?project=${project.id}`);
-  expect(await screen.findByRole("combobox", { name: "Project" })).toHaveValue(project.id);
+  expect(await screen.findByRole("heading", { name: project.name })).toBeInTheDocument();
   expect(await screen.findByRole("region", { name: "Sources" })).toBeInTheDocument();
 });
 
-it("cancels the new-project form and clears the project back to none", async () => {
-  server.use(
-    http.get("*/api/projects", () => HttpResponse.json([project])),
-    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
-    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
-  );
-  const { router, user } = renderApp(`/new?project=${project.id}`);
+it("cancels the new-project form and leaves the URL without a project", async () => {
+  server.use(http.get("*/api/projects", () => HttpResponse.json([project])));
+  const { router, user } = renderApp("/new");
   await user.click(await screen.findByRole("button", { name: "New project" }));
   await user.click(screen.getByRole("button", { name: "Cancel" }));
   expect(screen.queryByRole("textbox", { name: "Project name" })).not.toBeInTheDocument();
@@ -125,9 +123,9 @@ it("does not carry a source selection across browser navigation to another proje
     http.get("*/api/runs", () => HttpResponse.json(noRuns)),
   );
   const { router, user } = renderApp(`/new?project=${project.id}`);
-  const box = await screen.findByRole("checkbox", { name: "Use port.txt in this run" });
+  const box = await screen.findByRole("checkbox", { name: "Use port.txt in this report" });
   await user.click(box);
   expect(box).not.toBeChecked();
   await act(() => router.navigate(`/new?project=${other.id}`));
-  expect(await screen.findByRole("checkbox", { name: "Use b.txt in this run" })).toBeChecked();
+  expect(await screen.findByRole("checkbox", { name: "Use b.txt in this report" })).toBeChecked();
 });
```

```diff
diff --git a/web/src/pages/new/SourcesPanel.test.tsx b/web/src/pages/new/SourcesPanel.test.tsx
index 166e2cf..1b7c5e9 100644
--- a/web/src/pages/new/SourcesPanel.test.tsx
+++ b/web/src/pages/new/SourcesPanel.test.tsx
@@ -20,7 +20,7 @@ it("lists the project's sources, all selected for the run by default, and toggle
   serve();
   const { user } = renderApp(`/new?project=${project.id}`);
   const region = await screen.findByRole("region", { name: "Sources" });
-  const boxes = await within(region).findAllByRole("checkbox", { name: /Use .* in this run/ });
+  const boxes = await within(region).findAllByRole("checkbox", { name: /Use .* in this report/ });
   expect(boxes).toHaveLength(2);
   expect(boxes.every((b) => (b as HTMLInputElement).checked)).toBe(true);
   expect(within(region).getByText("letter.coglossa.json")).toBeInTheDocument();
@@ -56,14 +56,16 @@ it("uploads a file, adds and selects it (test_upload_adds_and_selects_the_source
     }),
   );
   const { router, user } = renderApp(`/new?project=${project.id}`);
-  const input = await screen.findByLabelText("Add a file");
-  await user.click(await screen.findByRole("checkbox", { name: "Use port.txt in this run" }));
+  const input = await screen.findByLabelText("Choose files");
+  await user.click(await screen.findByRole("checkbox", { name: "Use port.txt in this report" }));
   await user.upload(input, new File(["# Notes"], "more.md", { type: "text/markdown" }));
   await user.click(screen.getByRole("button", { name: "Upload" }));
-  const row = await screen.findByText("more.md");
-  expect(row).toBeInTheDocument();
-  expect(screen.getByRole("checkbox", { name: "Use more.md in this run" })).toBeChecked();
-  expect(screen.getByRole("checkbox", { name: "Use port.txt in this run" })).not.toBeChecked();
+  expect(await screen.findByRole("checkbox", { name: "Use more.md in this report" })).toBeChecked();
+  // the uploaded file's chip is gone
+  expect(
+    within(screen.getByRole("list", { name: "Chosen files" })).queryByText("more.md"),
+  ).toBeNull();
+  expect(screen.getByRole("checkbox", { name: "Use port.txt in this report" })).not.toBeChecked();
   expect((input as HTMLInputElement).value).toBe("");
   // the choice in the URL gained the new source (R-M17-6)
   expect(new URLSearchParams(router.state.location.search).get("sources")).toBe(
@@ -87,12 +89,12 @@ it("an upload while every source is selected keeps every source selected, and th
   );
   const { router, user } = renderApp(`/new?project=${project.id}`);
   await user.upload(
-    await screen.findByLabelText("Add a file"),
+    await screen.findByLabelText("Choose files"),
     new File(["# Notes"], "more.md", { type: "text/markdown" }),
   );
   await user.click(screen.getByRole("button", { name: "Upload" }));
-  expect(await screen.findByRole("checkbox", { name: "Use more.md in this run" })).toBeChecked();
-  expect(screen.getByRole("checkbox", { name: "Use port.txt in this run" })).toBeChecked();
+  expect(await screen.findByRole("checkbox", { name: "Use more.md in this report" })).toBeChecked();
+  expect(screen.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeChecked();
   expect(router.state.location.search).toBe(`?project=${project.id}`);
 });
 
@@ -109,11 +111,15 @@ it("shows an upload rejection inline and keeps the form (test_upload_rejection_s
     ),
   );
   const { user } = renderApp(`/new?project=${project.id}`);
-  const input = await screen.findByLabelText("Add a file");
+  const input = await screen.findByLabelText("Choose files");
   await user.upload(input, new File(["x"], "big.pdf", { type: "application/pdf" }));
   await user.click(screen.getByRole("button", { name: "Upload" }));
-  expect(await screen.findByRole("alert")).toHaveTextContent("larger than the 1 MB upload limit");
-  expect(screen.getByRole("checkbox", { name: "Use port.txt in this run" })).toBeInTheDocument();
+  // the API's 413 names the limit, so its own line is shown on the file's chip
+  expect(await screen.findByRole("alert")).toHaveTextContent(
+    "big.pdf: big.pdf is larger than the 1 MB upload limit",
+  );
+  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
+  expect(screen.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeInTheDocument();
   expect((input as HTMLInputElement).value).toBe("");
 });
 
@@ -121,7 +127,7 @@ it("hides the Coglossa fetch when it is not configured", async () => {
   serve([source]);
   renderApp(`/new?project=${project.id}`);
   await screen.findByRole("region", { name: "Sources" });
-  await screen.findByRole("checkbox", { name: "Use port.txt in this run" });
+  await screen.findByRole("checkbox", { name: "Use port.txt in this report" });
   expect(screen.queryByRole("textbox", { name: "Coglossa run id" })).not.toBeInTheDocument();
 });
 
@@ -140,15 +146,17 @@ it("imports from Coglossa by run id and selects the imported source", async () =
   );
   const { user } = renderApp(`/new?project=${project.id}`);
   const field = await screen.findByRole("textbox", { name: "Coglossa run id" });
-  await user.click(await screen.findByRole("checkbox", { name: `Use ${source.name} in this run` }));
+  await user.click(
+    await screen.findByRole("checkbox", { name: `Use ${source.name} in this report` }),
+  );
   await user.type(field, "run-42");
   await user.click(screen.getByRole("button", { name: "Fetch from Coglossa" }));
   await waitFor(() => expect(field).toHaveValue(""));
   expect(
-    await screen.findByRole("checkbox", { name: `Use ${sources[1]!.name} in this run` }),
+    await screen.findByRole("checkbox", { name: `Use ${sources[1]!.name} in this report` }),
   ).toBeChecked();
   expect(
-    screen.getByRole("checkbox", { name: `Use ${source.name} in this run` }),
+    screen.getByRole("checkbox", { name: `Use ${source.name} in this report` }),
   ).not.toBeChecked();
 });
```

```diff
diff --git a/web/src/pages/new/RunOptions.test.tsx b/web/src/pages/new/RunOptions.test.tsx
index 59cb190..5170797 100644
--- a/web/src/pages/new/RunOptions.test.tsx
+++ b/web/src/pages/new/RunOptions.test.tsx
@@ -14,10 +14,12 @@ function Host() {
   );
 }
 
-it("clamps the iterations to 0-10 and treats junk as 0", async () => {
+it("clamps the revision rounds to 0-10 and treats junk as 0", async () => {
   server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
   const { user } = renderWithClient(<Host />);
-  const box = screen.getByRole("spinbutton", { name: "Audit iterations" });
+  const fold = screen.getByText("More options").closest("details")!;
+  expect(fold).not.toHaveAttribute("open"); // folded until asked (M18 spec §5.2)
+  const box = screen.getByRole("spinbutton", { name: "Revision rounds" });
   await user.clear(box);
   await user.type(box, "99");
   expect(box).toHaveValue(10);
@@ -25,10 +27,10 @@ it("clamps the iterations to 0-10 and treats junk as 0", async () => {
   expect(box).toHaveValue(0);
 });
 
-it("labels the empty option with the base pack, or the default profile when one is set", async () => {
+it("labels the empty option as no team profile, or the default profile when one is set", async () => {
   server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
   renderWithClient(<Host />);
-  expect(await screen.findByRole("option", { name: /^Base pack \(/ })).toBeInTheDocument();
+  expect(await screen.findByRole("option", { name: "No team profile" })).toHaveValue("");
   cleanup();
   server.use(
     http.get("*/api/system/info", () =>
@@ -36,12 +38,10 @@ it("labels the empty option with the base pack, or the default profile when one
     ),
   );
   renderWithClient(<Host />);
-  expect(await screen.findByRole("option", { name: "Default profile (team-east)" })).toHaveValue(
-    "",
-  );
+  expect(await screen.findByRole("option", { name: "Default (team-east)" })).toHaveValue("");
 });
 
-it("goes back to the base pack and shows a packs failure", async () => {
+it("goes back to no team profile and shows a packs failure", async () => {
   server.use(
     http.get("*/api/packs", () =>
       HttpResponse.json({ detail: "packs unavailable" }, { status: 404 }),
@@ -49,7 +49,7 @@ it("goes back to the base pack and shows a packs failure", async () => {
   );
   const { user } = renderWithClient(<Host />);
   expect(await screen.findByRole("alert")).toHaveTextContent("packs unavailable");
-  const profile = screen.getByRole("combobox", { name: "Profile" });
+  const profile = screen.getByRole("combobox", { name: "Team profile" });
   await user.selectOptions(profile, "");
   expect(profile).toHaveValue("");
 });
```

```diff
diff --git a/web/src/pages/new/RunList.test.tsx b/web/src/pages/new/RunList.test.tsx
index bc869e5..e80abf1 100644
--- a/web/src/pages/new/RunList.test.tsx
+++ b/web/src/pages/new/RunList.test.tsx
@@ -58,7 +58,7 @@ function servePaged(all: RunSummary[], options: { failOnce?: string } = {}) {
   return asked;
 }
 
-it("lists the project's runs with links to progress or review", async () => {
+it("lists the project's reports with links to progress or review", async () => {
   const running = {
     ...runSummary,
     run_id: "66666666-6666-6666-6666-666666666666",
@@ -68,8 +68,8 @@ it("lists the project's runs with links to progress or review", async () => {
   };
   serveRuns([running, runSummary]);
   renderApp(`/new?project=${project.id}`);
-  const table = await screen.findByRole("table", { name: "Runs" });
-  const rows = within(table).getAllByRole("row").slice(1);
+  const table = await screen.findByRole("list", { name: "Reports" });
+  const rows = within(table).getAllByRole("listitem");
   expect(rows).toHaveLength(2);
   expect(within(rows[0]!).getByRole("link", { name: "Progress" })).toHaveAttribute(
     "href",
@@ -79,7 +79,8 @@ it("lists the project's runs with links to progress or review", async () => {
     "href",
     `/runs/${runSummary.run_id}/review`,
   );
-  expect(within(rows[1]!).getByText("Completed")).toBeInTheDocument();
+  expect(within(rows[1]!).getByText("to review")).toBeInTheDocument();
+  expect(within(rows[0]!).getByText("writing")).toBeInTheDocument();
   expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
 });
 
@@ -101,24 +102,22 @@ it("shows an error when the run list fails", async () => {
   serveRuns(HttpResponse.json({ detail: "runs unavailable" }, { status: 400 }));
   renderApp(`/new?project=${project.id}`);
   expect(await screen.findByRole("alert")).toHaveTextContent("runs unavailable");
-  expect(screen.queryByRole("table", { name: "Runs" })).not.toBeInTheDocument();
+  expect(screen.queryByRole("list", { name: "Reports" })).not.toBeInTheDocument();
 });
 
 it("pages fifty at a time by cursor and stops at the last page", async () => {
   const all = many(120);
   const asked = servePaged(all);
   const { user } = renderApp(`/new?project=${project.id}`);
-  const table = await screen.findByRole("table", { name: "Runs" });
-  expect(within(table).getAllByRole("row")).toHaveLength(RUN_PAGE + 1);
+  const table = await screen.findByRole("list", { name: "Reports" });
+  expect(within(table).getAllByRole("listitem")).toHaveLength(RUN_PAGE);
   await user.click(screen.getByRole("button", { name: "Show more" }));
-  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(101));
+  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(100));
   await user.click(screen.getByRole("button", { name: "Show more" }));
-  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(121));
+  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(120));
   expect(asked).toEqual([`50:-`, `50:${cursorOf(all[49]!)}`, `50:${cursorOf(all[99]!)}`]);
   expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
-  const values = within(table)
-    .getAllByRole("cell")
-    .filter((c) => c.dir === "auto");
+  const values = [...table.querySelectorAll(".statement")];
   expect(new Set(values.map((c) => c.textContent)).size).toBe(120); // no run twice
 });
 
@@ -135,25 +134,25 @@ it("keeps Show more in place, disabled, while the next page loads", async () =>
     }),
   );
   const { user } = renderApp(`/new?project=${project.id}`);
-  const table = await screen.findByRole("table", { name: "Runs" });
+  const table = await screen.findByRole("list", { name: "Reports" });
   await user.click(screen.getByRole("button", { name: "Show more" }));
   expect(screen.getByRole("button", { name: "Show more" })).toBeDisabled();
   nextPage.resolve();
-  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(101));
+  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(100));
   await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
 });
 
 it("pages past 500 runs to the oldest, with no ceiling", async () => {
   servePaged(many(520));
   const { user } = renderApp(`/new?project=${project.id}`);
-  const table = await screen.findByRole("table", { name: "Runs" });
-  const rows = () => table.querySelectorAll("tbody tr").length; // 520 rows: skip role queries
+  const table = await screen.findByRole("list", { name: "Reports" });
+  const rows = () => table.querySelectorAll("li").length; // 520 rows: skip role queries
   for (let shown = RUN_PAGE; shown < 520; shown += RUN_PAGE) {
     await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
     await user.click(screen.getByRole("button", { name: "Show more" }));
     await waitFor(() => expect(rows()).toBe(Math.min(shown + RUN_PAGE, 520)));
   }
-  expect(table.querySelector("tbody tr:last-child")).toHaveTextContent("Statement 519");
+  expect(table.querySelector("li:last-child")).toHaveTextContent("Statement 519");
   expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
   expect(screen.queryByText(/Showing the newest/)).not.toBeInTheDocument();
 });
@@ -162,15 +161,15 @@ it("keeps the rows when the next page fails, and Show more tries again", async (
   const all = many(80);
   servePaged(all, { failOnce: cursorOf(all[49]!) });
   const { user } = renderApp(`/new?project=${project.id}`);
-  const table = await screen.findByRole("table", { name: "Runs" });
+  const table = await screen.findByRole("list", { name: "Reports" });
   await user.click(screen.getByRole("button", { name: "Show more" }));
   expect(await screen.findByRole("alert")).toHaveTextContent(
     "the database is unavailable: connection reset",
   );
-  expect(within(table).getAllByRole("row")).toHaveLength(RUN_PAGE + 1);
+  expect(within(table).getAllByRole("listitem")).toHaveLength(RUN_PAGE);
   await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
   await user.click(screen.getByRole("button", { name: "Show more" }));
-  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(81));
+  await waitFor(() => expect(within(table).getAllByRole("listitem")).toHaveLength(80));
   expect(screen.queryByRole("alert")).not.toBeInTheDocument();
 });
 
@@ -190,10 +189,11 @@ it("starts each project's run list at the first page again", async () => {
     }),
   );
   const { user } = renderApp(`/new?project=${project.id}`);
-  await screen.findByRole("table", { name: "Runs" });
+  await screen.findByRole("list", { name: "Reports" });
   await user.click(screen.getByRole("button", { name: "Show more" }));
   await waitFor(() => expect(asked).toContain(`${project.id}:page-2`));
-  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), other.id);
+  const sidebar = screen.getByRole("navigation", { name: "Your projects" });
+  await user.click(within(sidebar).getByRole("link", { name: /^Danube/ }));
   await waitFor(() => expect(asked).toContain(`${other.id}:-`));
   expect(asked).not.toContain(`${other.id}:page-2`); // the next page did not carry over
   // siblings with one key kept the old value statement on screen after a switch
@@ -201,3 +201,47 @@ it("starts each project's run list at the first page again", async () => {
   expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
   errors.mockRestore();
 });
+
+it("says when each report was written, its status in words and symbol, and its decision", async () => {
+  const at = new Date(Date.now() - 3 * 3_600_000).toISOString();
+  serveRuns([
+    {
+      ...runSummary,
+      run_id: "a1111111-0000-0000-0000-000000000000",
+      created_at: at,
+      review_decision: "accepted",
+    },
+    {
+      ...runSummary,
+      run_id: "a2222222-0000-0000-0000-000000000000",
+      created_at: at,
+      review_decision: "returned",
+    },
+    {
+      ...runSummary,
+      run_id: "a3333333-0000-0000-0000-000000000000",
+      created_at: at,
+      review_decision: "returned",
+      review_child_state: "cancelled",
+    },
+    {
+      ...runSummary,
+      run_id: "a4444444-0000-0000-0000-000000000000",
+      created_at: at,
+      state: "gate_rejected",
+    },
+  ]);
+  renderApp(`/new?project=${project.id}`);
+  const rows = within(await screen.findByRole("list", { name: "Reports" })).getAllByRole(
+    "listitem",
+  );
+  expect(rows.map((r) => r.querySelector(".status")!.textContent)).toEqual([
+    "✓ accepted",
+    "↺ returned",
+    "● to review", // its revision was stopped: to review again (R-M15-1)
+    "⚠ not supported by the sources",
+  ]);
+  const when = within(rows[0]!).getByText("3 hours ago");
+  expect(when).toHaveAttribute("title", new Date(at).toLocaleString());
+  expect(when.tagName).toBe("TIME");
+});
```

```diff
diff --git a/web/src/pages/new/Suggestions.test.tsx b/web/src/pages/new/Suggestions.test.tsx
index 0aefa21..f4aba81 100644
--- a/web/src/pages/new/Suggestions.test.tsx
+++ b/web/src/pages/new/Suggestions.test.tsx
@@ -51,7 +51,7 @@ function serveSequence(
   return () => served;
 }
 
-const WAITING = "Waiting for the worker to start the discovery…";
+const WAITING = "Waiting for Corelata to start looking…";
 const LOOKING = "Looking for value in the selected sources…";
 const NOT_STARTED =
   "Discovery did not start within 60 minutes and was stopped: the worker was stopped or busy with runs. Start a new discovery.";
@@ -69,7 +69,7 @@ it("says it waits for the worker until the worker starts the discovery (R-M17-28
   renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
   const waiting = await screen.findByText(WAITING);
   expect(waiting).toHaveAttribute("role", "status"); // a polite live region
-  expect(waiting).toHaveAccessibleName("Discovery");
+  expect(waiting).toHaveAccessibleName("Suggestions");
   expect(await screen.findByText(LOOKING, {}, { timeout: 5000 })).toHaveAttribute("role", "status");
   expect(screen.queryByText(WAITING)).not.toBeInTheDocument();
 });
@@ -251,7 +251,7 @@ it("says so when no value statement was found", async () => {
   ).toBeInTheDocument();
 });
 
-it("shows one evidence unit in the singular and omits an empty note", async () => {
+it("shows one passage in the singular and omits an empty note", async () => {
   serveView(
     discoveryView({
       state: "completed",
@@ -261,10 +261,10 @@ it("shows one evidence unit in the singular and omits an empty note", async () =
     }),
   );
   renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
-  expect(await screen.findByText(/1 evidence unit$/)).toBeInTheDocument();
+  expect(await screen.findByText(/· 1 passage$/)).toBeInTheDocument();
 });
 
-it("treats a candidate without evidence as zero units", async () => {
+it("treats a candidate without evidence as zero passages", async () => {
   serveView(
     discoveryView({
       state: "completed",
@@ -272,13 +272,13 @@ it("treats a candidate without evidence as zero units", async () => {
     }),
   );
   renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
-  expect(await screen.findByText(/0 evidence units/)).toBeInTheDocument();
+  expect(await screen.findByText(/· 0 passages$/)).toBeInTheDocument();
 });
 
 it("falls back to a generic message for a failure without text", async () => {
   serveView(discoveryView({ state: "failed" }));
   renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
-  expect(await screen.findByRole("alert")).toHaveTextContent("The discovery failed.");
+  expect(await screen.findByRole("alert")).toHaveTextContent("No suggestions could be made.");
 });
 
 it("shows a request error", async () => {
```

```diff
diff --git a/web/src/pages/new/ValueStatement.test.tsx b/web/src/pages/new/ValueStatement.test.tsx
index 925e7a6..e0af466 100644
--- a/web/src/pages/new/ValueStatement.test.tsx
+++ b/web/src/pages/new/ValueStatement.test.tsx
@@ -41,7 +41,7 @@ it("suggests values from a discovery and fills the statement (test_suggest_value
   );
   const { user } = renderRoute(<Host sourceIds={[source.id]} />, PAGE);
   await user.click(screen.getByRole("button", { name: "Suggest value" }));
-  expect(await screen.findByRole("status", { name: "Discovery" })).toHaveTextContent(
+  expect(await screen.findByRole("status", { name: "Suggestions" })).toHaveTextContent(
     "Looking for value",
   );
   const list = await screen.findByRole("list", { name: "Suggested value statements" });
@@ -79,7 +79,7 @@ it("keeps the discovery in the URL, so a reload reads it again (R-M16-14)", asyn
     expect(router.state.location.search).toBe(`?project=${project.id}&discovery=${other}`),
   );
   expect(router.state.historyAction).toBe("REPLACE");
-  expect(await screen.findByRole("status", { name: "Discovery" })).toHaveTextContent(
+  expect(await screen.findByRole("status", { name: "Suggestions" })).toHaveTextContent(
     "Looking for value",
   );
 });
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/pages/new`
Expected: FAIL: `Failed to resolve import "./AddSources"`; the page tests find no "Write the report" button, no "Use port.txt in this report" checkbox, no "Reports" list, no "Team profile" select; the switching tests find no sidebar link that changes the URL to `?project=<other>`.

- [ ] **Step 3: Add sources (R-M18-15, R-M18-11)**

Create `web/src/pages/new/AddSources.tsx` (adapted from Coglossa's `translate/DropArea.tsx`):

```tsx
import { useId, useState } from "react";
import { ApiError, errorText } from "../../api/client";
import { useUploadSource } from "../../api/projects";
import type { SourceKind, SourceView } from "../../api/types";
import { messageOf } from "../../components/ErrorMessage";

/** The file types the API parses (spec §5): the same list as before M18. */
export const ACCEPTED = [".docx", ".pdf", ".txt", ".md", ".html", ".htm", ".json", ".csv"];

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
}: {
  projectId: string;
  maxUploadMb: number;
  onAdded: (added: SourceView[]) => void;
}) {
  const upload = useUploadSource(projectId);
  const [kind, setKind] = useState<SourceKind>("file");
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
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
    for (const item of items) {
      patch(item.key, { uploading: true, error: null });
      try {
        const added = await upload.mutateAsync({ file: item.file, kind });
        setChosen((current) => current.filter((c) => c.key !== item.key));
        onAdded(added);
      } catch (error) {
        patch(item.key, { uploading: false, error: uploadErrorText(error) });
      }
    }
    setBusy(false);
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
            <li key={c.key} className={why ? "chip bad" : "chip"}>
              <span dir="auto">{c.file.name}</span>{" "}
              <span className="muted">{sizeText(c.file.size)}</span>
              {c.uploading ? <span className="muted"> uploading…</span> : null}
              {why ? (
                <span role="alert" className="error" dir="auto">
                  {why}
                </span>
              ) : null}
              {c.error ? (
                <button type="button" onClick={() => void send([c])} disabled={busy}>
                  Try again
                </button>
              ) : null}
              <button
                type="button"
                className="quiet"
                aria-label={`Remove ${c.file.name}`}
                disabled={c.uploading}
                onClick={() => setChosen((current) => current.filter((x) => x.key !== c.key))}
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
```

`git rm web/src/pages/new/UploadSource.tsx`. The Sources card:

```tsx
import { useInfo } from "../../api/system";
import { useSources } from "../../api/projects";
import type { SourceView } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { AddSources } from "./AddSources";
import { FetchFromCoglossa } from "./FetchFromCoglossa";

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
            <li key={s.id}>
              <label className="row">
                <input
                  type="checkbox"
                  aria-label={`Use ${s.name} in this report`}
                  checked={selected.has(s.id)}
                  onChange={(event) => onToggle(s.id, event.target.checked)}
                />
                <span dir="auto">{s.name}</span>
                <span className="badge">{kindText(s)}</span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}
      {list.length > 0 ? (
        <p role="status" aria-label="Selected sources" className="muted">
          {list.filter((s) => selected.has(s.id)).length} of {list.length} selected
        </p>
      ) : null}
      <AddSources
        projectId={projectId}
        maxUploadMb={info.data?.max_upload_mb ?? 200}
        onAdded={onAdded}
      />
      {info.data?.coglossa ? <FetchFromCoglossa projectId={projectId} onAdded={onAdded} /> : null}
    </section>
  );
}
```

```diff
diff --git a/web/src/pages/new/FetchFromCoglossa.tsx b/web/src/pages/new/FetchFromCoglossa.tsx
index 18523f9..9eb5c8c 100644
--- a/web/src/pages/new/FetchFromCoglossa.tsx
+++ b/web/src/pages/new/FetchFromCoglossa.tsx
@@ -30,7 +30,7 @@ export function FetchFromCoglossa({
         Coglossa run id
       </label>
       <input id={id} value={runId} onChange={(event) => setRunId(event.target.value)} />
-      <button type="submit" className="secondary" disabled={!runId.trim() || fetchRun.isPending}>
+      <button type="submit" disabled={!runId.trim() || fetchRun.isPending}>
         {fetchRun.isPending ? "Fetching…" : "Fetch from Coglossa"}
       </button>
       {fetchRun.error ? <ErrorMessage error={fetchRun.error} /> : null}
```

- [ ] **Step 4: The value statement, the options, the reports**

```diff
diff --git a/web/src/pages/new/ValueStatement.tsx b/web/src/pages/new/ValueStatement.tsx
index a879d2f..5c03bf9 100644
--- a/web/src/pages/new/ValueStatement.tsx
+++ b/web/src/pages/new/ValueStatement.tsx
@@ -45,7 +45,7 @@ export function ValueStatement({
   }
 
   return (
-    <section aria-label="Value statement" className="panel">
+    <section aria-label="Value statement" className="card">
       <div className="field">
         <label htmlFor={id}>Value statement</label>
         <textarea
@@ -58,7 +58,7 @@ export function ValueStatement({
         />
       </div>
       <div className="row">
-        <button type="button" className="secondary" onClick={suggest} disabled={!canSuggest}>
+        <button type="button" onClick={suggest} disabled={!canSuggest}>
           Suggest value
         </button>
         {sourceIds.length === 0 ? (
```

```diff
diff --git a/web/src/pages/new/Suggestions.tsx b/web/src/pages/new/Suggestions.tsx
index 25b3174..0fe6da9 100644
--- a/web/src/pages/new/Suggestions.tsx
+++ b/web/src/pages/new/Suggestions.tsx
@@ -1,5 +1,6 @@
 import { DISCOVERY_STALLED, discoveryStalled, useDiscovery } from "../../api/discoveries";
 import { ErrorMessage } from "../../components/ErrorMessage";
+import { plural } from "../../lib/words";
 
 export function Suggestions({
   discoveryId,
@@ -14,28 +15,28 @@ export function Suggestions({
   if (discoveryStalled(view)) {
     // Polling has stopped (R-M16-2); role="status" is a polite live region.
     return (
-      <p role="status" aria-label="Discovery" className="muted">
+      <p role="status" aria-label="Suggestions" className="muted">
         {DISCOVERY_STALLED}
       </p>
     );
   }
   if (view?.state === "created") {
-    // queued behind runs, or no worker running: the server's start limit applies (R-M17-28)
+    // queued behind reports, or no worker running: the server's start limit applies (R-M17-28)
     return (
-      <p role="status" aria-label="Discovery" className="muted">
-        Waiting for the worker to start the discovery…
+      <p role="status" aria-label="Suggestions" className="muted">
+        Waiting for Corelata to start looking…
       </p>
     );
   }
   if (!view || view.state === "running") {
     return (
-      <p role="status" aria-label="Discovery" className="muted">
+      <p role="status" aria-label="Suggestions" className="muted">
         Looking for value in the selected sources…
       </p>
     );
   }
   if (view.state === "failed")
-    return <ErrorMessage error={new Error(view.error ?? "The discovery failed.")} />;
+    return <ErrorMessage error={new Error(view.error ?? "No suggestions could be made.")} />;
   const candidates = view.candidates ?? [];
   if (candidates.length === 0)
     return <p className="muted">No value statement was found in these sources.</p>;
@@ -49,11 +50,10 @@ export function Suggestions({
               <strong>{c.text}</strong>
             </p>
             <p className="muted">
-              For <span dir="auto">{c.audience}</span> · {evidenceCount} evidence unit
-              {evidenceCount === 1 ? "" : "s"}
+              For <span dir="auto">{c.audience}</span> · {plural(evidenceCount, "passage")}
             </p>
             {c.confidence_note ? <p className="muted">{c.confidence_note}</p> : null}
-            <button type="button" className="secondary" onClick={() => onPick(c.text)}>
+            <button type="button" onClick={() => onPick(c.text)}>
               Use this statement
             </button>
           </li>
```

Replace `web/src/pages/new/RunOptions.tsx` (the More options fold):

```tsx
import { useId } from "react";
import { usePacks } from "../../api/packs";
import { useInfo } from "../../api/system";
import { ErrorMessage } from "../../components/ErrorMessage";

/** The project page's More options fold, closed (M18 spec §5.2): the team profile and the
 * revision rounds, as before M18. */
export function RunOptions({
  profile,
  onProfile,
  maxIterations,
  onMaxIterations,
}: {
  profile: string | null;
  onProfile: (profile: string | null) => void;
  maxIterations: number;
  onMaxIterations: (n: number) => void;
}) {
  const info = useInfo();
  const packs = usePacks();
  const pack = (packs.data ?? []).find((p) => p.name === info.data?.default_pack);
  const profileId = useId();
  const roundsId = useId();
  return (
    <details className="card options">
      <summary>More options</summary>
      <div className="row">
        <div className="field">
          <label htmlFor={profileId}>Team profile</label>
          <select
            id={profileId}
            value={profile ?? ""}
            onChange={(e) => onProfile(e.target.value || null)}
          >
            <option value="">
              {info.data?.default_profile
                ? `Default (${info.data.default_profile})`
                : "No team profile"}
            </option>
            {(pack?.profiles ?? []).map((p) => (
              <option key={p.name} value={p.name} disabled={p.draft}>
                {p.name}
                {p.draft ? " (draft)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={roundsId}>Revision rounds</label>
          <input
            id={roundsId}
            type="number"
            min={0}
            max={10}
            value={maxIterations}
            onChange={(e) =>
              onMaxIterations(Math.min(10, Math.max(0, Number(e.target.value) || 0)))
            }
          />
        </div>
      </div>
      {packs.error ? <ErrorMessage error={packs.error} /> : null}
    </details>
  );
}
```

Replace `web/src/pages/new/RunList.tsx` (the Reports card, as rows):

```tsx
import { Link } from "react-router";
import { useRuns } from "../../api/projects";
import type { RunSummary } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { StatusText } from "../../components/StatusText";
import { whenText } from "../../lib/dates";
import { formatDateTime, isTerminal } from "../../lib/format";
import { fromSummary, runStatus } from "../../lib/status";

function OpenLink({ run }: { run: RunSummary }) {
  if (run.state === "completed") return <Link to={`/runs/${run.run_id}/review`}>Review</Link>;
  return <Link to={`/runs/${run.run_id}`}>{isTerminal(run.state) ? "Outcome" : "Progress"}</Link>;
}

/** The project page's Reports card (M18 spec §5.2): newest first, paged by cursor as before. */
export function RunList({ projectId }: { projectId: string }) {
  const runs = useRuns(projectId);
  const rows = runs.data?.pages.flatMap((page) => page.runs) ?? [];
  if (runs.error && rows.length === 0) return <ErrorMessage error={runs.error} />;
  if (rows.length === 0) return null;
  return (
    <section aria-label="Reports" className="card">
      <h2>Reports</h2>
      <ul aria-label="Reports" className="report-list">
        {rows.map((run) => (
          <li key={run.run_id} className="report-row">
            <time dateTime={run.created_at} title={formatDateTime(run.created_at)}>
              {whenText(run.created_at)}
            </time>
            <span className="statement" dir="auto">
              {run.value_statement}
            </span>
            <StatusText status={runStatus(fromSummary(run))} />
            <OpenLink run={run} />
          </li>
        ))}
      </ul>
      {/* a failed next page (or refresh) keeps the rows shown; Show more tries again */}
      {runs.error ? <ErrorMessage error={runs.error} /> : null}
      {runs.hasNextPage ? (
        <button type="button" disabled={runs.isFetching} onClick={() => void runs.fetchNextPage()}>
          Show more
        </button>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 5: The two screens**

```diff
diff --git a/web/src/pages/new/ProjectPicker.tsx b/web/src/pages/new/ProjectPicker.tsx
index 301b63c..d696857 100644
--- a/web/src/pages/new/ProjectPicker.tsx
+++ b/web/src/pages/new/ProjectPicker.tsx
@@ -3,6 +3,7 @@ import { useCreateProject, useProjects } from "../../api/projects";
 import { ErrorMessage } from "../../components/ErrorMessage";
 import { Loading } from "../../components/Loading";
 
+/** New report without a project (M18 spec §5.1): choose one, or create one. */
 export function ProjectPicker({
   projectId,
   onChange,
@@ -34,7 +35,8 @@ export function ProjectPicker({
   }
 
   return (
-    <section aria-label="Project" className="panel">
+    <section aria-label="Project" className="card">
+      <h2>Which project is it for?</h2>
       {projects.isPending ? (
         <Loading what="Loading projects" />
       ) : (
@@ -54,7 +56,7 @@ export function ProjectPicker({
               ))}
             </select>
             {creating ? null : (
-              <button type="button" className="secondary" onClick={() => setCreating(true)}>
+              <button type="button" onClick={() => setCreating(true)}>
                 New project
               </button>
             )}
@@ -74,10 +76,10 @@ export function ProjectPicker({
             onChange={(event) => setName(event.target.value)}
             dir="auto"
           />
-          <button type="submit" disabled={!name.trim() || create.isPending}>
+          <button type="submit" className="primary" disabled={!name.trim() || create.isPending}>
             Create
           </button>
-          <button type="button" className="secondary" onClick={cancel}>
+          <button type="button" onClick={cancel}>
             Cancel
           </button>
         </form>
```

Replace `web/src/pages/new/NewRunPage.tsx`:

```tsx
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useProjects, useSources } from "../../api/projects";
import { useStartRun } from "../../api/runs";
import type { SourceView } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useActiveProject, useDocumentTitle } from "../../components/frame";
import { ProjectPicker } from "./ProjectPicker";
import { RunList } from "./RunList";
import { RunOptions } from "./RunOptions";
import { SourcesPanel } from "./SourcesPanel";
import { ValueStatement } from "./ValueStatement";

/** The chosen sources' URL parameter: `sources=<id>,<id>` (CRL-40, R-M17-6). */
export const SOURCES_PARAM = "sources";

/** M18 spec §5.1 and §5.2: New report without a project, and the project page. The project,
 * the discovery (R-M16-14) and the chosen sources live in the URL, so a reload keeps them; the
 * statement and the options live here until Write the report. The sidebar switches projects:
 * its links name the project alone, so another project drops the discovery and the sources. */
export function NewRunPage() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get("project");
  useActiveProject(projectId);
  const projects = useProjects();
  const current = (projects.data ?? []).find((p) => p.id === projectId);
  useDocumentTitle(
    projectId === null ? "New report – Corelata" : current ? `${current.name} – Corelata` : null,
  );
  const sources = useSources(projectId);
  // Without the parameter every source is selected, new ones too. Ids that are not the
  // project's (removed, or a link from another project) are dropped without a word.
  const listed = params.get(SOURCES_PARAM);
  const selected: ReadonlySet<string> = useMemo(() => {
    const ids = (sources.data ?? []).map((s) => s.id);
    if (listed === null) return new Set(ids);
    const chosen = new Set(listed.split(","));
    return new Set(ids.filter((id) => chosen.has(id)));
  }, [listed, sources.data]);
  const choose = useCallback(
    (next: ReadonlySet<string>) =>
      // replace, as for the discovery: Back does not step through every tick of a checkbox
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          updated.set(SOURCES_PARAM, [...next].join(","));
          return updated;
        },
        { replace: true },
      ),
    [setParams],
  );

  const navigate = useNavigate();
  const start = useStartRun();
  const [statement, setStatement] = useState("");
  const [profile, setProfile] = useState<string | null>(null); // null: the deployment's default
  const [maxIterations, setMaxIterations] = useState(2);
  const sourceIds = (sources.data ?? []).filter((s) => selected.has(s.id)).map((s) => s.id);
  const canStart =
    Boolean(projectId) && statement.trim().length > 0 && sourceIds.length > 0 && !start.isPending;

  function startRun() {
    if (!projectId) return;
    start.mutate(
      {
        project_id: projectId,
        source_ids: sourceIds,
        value_statement: statement.trim(),
        profile,
        max_iterations: maxIterations,
        extra_guidance: "",
      },
      { onSuccess: (run) => navigate(`/runs/${run.run_id}`) },
    );
  }

  // choosing a project names it alone: no discovery, no chosen sources (R-M16-14, R-M17-6)
  const changeProject = useCallback(
    (id: string) => setParams(id ? { project: id } : {}),
    [setParams],
  );
  const toggle = useCallback(
    (sourceId: string, on: boolean) => {
      const next = new Set(selected);
      if (on) next.add(sourceId);
      else next.delete(sourceId);
      choose(next);
    },
    [selected, choose],
  );
  const added = useCallback(
    (list: SourceView[]) => {
      if (listed === null) return; // every source is selected already, the new ones too
      choose(new Set([...selected, ...list.map((s) => s.id)]));
    },
    [listed, selected, choose],
  );

  if (!projectId) {
    return (
      <article className="new-report">
        <h1>New report</h1>
        <ProjectPicker projectId={null} onChange={changeProject} />
      </article>
    );
  }
  return (
    <article className="project-page" key={projectId}>
      <p className="eyebrow">Project</p>
      <h1 dir="auto">{current?.name ?? "Project"}</h1>
      <SourcesPanel projectId={projectId} selected={selected} onToggle={toggle} onAdded={added} />
      <ValueStatement
        projectId={projectId}
        sourceIds={sourceIds}
        value={statement}
        onChange={setStatement}
      />
      <RunOptions
        profile={profile}
        onProfile={setProfile}
        maxIterations={maxIterations}
        onMaxIterations={setMaxIterations}
      />
      <div className="row write">
        <button type="button" className="primary" onClick={startRun} disabled={!canStart}>
          {start.isPending ? "Starting…" : "Write the report"}
        </button>
        {sourceIds.length === 0 && sources.data ? (
          <span className="muted">Choose at least one source.</span>
        ) : null}
        {start.error ? <ErrorMessage error={start.error} /> : null}
      </div>
      <RunList projectId={projectId} />
    </article>
  );
}
```

Replace `web/src/styles/new.css`:

```css
/* New report and the project page (spec §5.1, §5.2). The drop area and the chips are adapted
   from Coglossa's translate.css. */
.new-report,
.project-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.new-report > h1,
.project-page > h1 {
  margin: 0;
}

.eyebrow {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}

.card {
  margin-bottom: 0;
}

.source-list,
.report-list,
.suggestions {
  list-style: none;
  margin: 0 0 var(--space-3);
  padding: 0;
}

.source-list li {
  padding: var(--space-1) 0;
}

.add-sources {
  margin-top: var(--space-4);
}

.drop-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  min-height: 7rem;
  padding: var(--space-5);
  border: 0.125rem dashed var(--border-strong);
  border-radius: var(--radius-2);
  background: var(--surface);
  cursor: pointer;
  text-align: center;
}

.drop-area.over {
  border-color: var(--accent);
  background: var(--selected);
}

/* The file input is visually hidden, so its focus shows on the drop area. */
.drop:has(> input[type="file"]:focus-visible) .drop-area {
  outline: 0.125rem solid var(--accent);
  outline-offset: 0.125rem;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  list-style: none;
  margin: var(--space-3) 0;
  padding: 0;
}

.chips:empty {
  margin: 0;
}

.chip {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius-1);
  background: var(--surface);
}

.chip.bad {
  border-color: var(--danger);
}

.suggestions li {
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-2);
  background: var(--surface-2);
}

.suggestions p {
  margin: 0 0 var(--space-2);
}

.options > summary {
  font-weight: 600;
}

.options .row {
  margin-top: var(--space-3);
  gap: var(--space-5);
}

.write .primary {
  padding: var(--space-3) var(--space-5);
}

.report-row {
  display: grid;
  grid-template-columns: 8rem minmax(0, 1fr) 12rem 6rem;
  gap: var(--space-3);
  align-items: baseline;
  padding: var(--space-2) 0;
  border-bottom: var(--border-width) solid var(--border);
}

.report-row time {
  color: var(--text-muted);
  font-size: var(--text-sm);
}
```

- [ ] **Step 6: Run the tests, lint and build**

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: clean; 354 passed in 50 files, coverage at least 95%. The pinned tests keep their assertions: "keeps the chosen sources in the URL…", "drops ids in the URL that are not the project's…", "a URL that names none of the project's sources selects none", "choosing another project drops the discovery and the chosen sources…", "a discovery that starts for the old project does not write itself…", the run list's cursor paging and the discovery polling tests.

- [ ] **Step 7: Commit**

```bash
cat > "$SCRATCH/m18-task5-commit.txt" <<'EOF'
feat(web): New report and the project page, drop-area uploads, Reports list (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/src/pages/new web/src/styles/new.css web/src/test/engine-words.ts
git -C "$REPO" commit -F "$SCRATCH/m18-task5-commit.txt"
```

(`git add web/src/pages/new` stages the deletion of `UploadSource.tsx` that `git rm` made.)

---

### Task 6: Writing the report: steps in words and symbols, Details, Stop, outcomes (spec §5.3)

**Files:**
- Delete: `web/src/components/StateBadge.tsx`
- Modify: `web/src/pages/run/StageTimeline.tsx`, `RunPage.tsx`, `RunOutcome.tsx`, `CancelRun.tsx` and the tests `StageTimeline.test.tsx`, `RunPage.test.tsx`, `RunOutcome.test.tsx`; `web/src/components/primitives.test.tsx`; `web/src/styles/run.css`; `web/src/test/server.ts`

**Interfaces:**
- Consumes: Task 4's `STEP_LABEL`, `PROGRESS_STEPS`, `REVISED_STEPS`, `plural`, `runStatus`, `fromProgress`, `useActiveProject`, `useDocumentTitle`, `useProjects`; `useReportJson` (unchanged).
- Produces: `StageTimeline.tsx`: `type StepStatus = "done" | "now" | "failed" | "pending"`, `STEP_MARK`, `type StepRow`, `stepRows(progress)`, `Steps({progress})`, `StageDetails({progress})`; `RunOutcome.tsx`: `outcomeHeading(progress)`, `RunOutcome({progress, openFindings?})`; names on screen: "Breadcrumb", "Writing the report", "Steps", "Details", "Stage details", "Stop writing…", "Stop this report?", "Stop", "Keep going", "Stopping after the current step…", "Review the report", "Try another statement", "Start a new report".

- [ ] **Step 1: Write the failing tests**

Replace `web/src/pages/run/StageTimeline.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { runProgress } from "../../test/fixtures";
import { StageDetails, stepRows, Steps } from "./StageTimeline";

const stage = (stage: string, iteration: number, ok = true, error: string | null = null) => ({
  stage,
  iteration,
  ok,
  error,
  output: null,
  started_at: "2026-10-13T10:02:00Z",
  finished_at: "2026-10-13T10:02:03Z",
});

it("derives one row per step from the recorded attempts and the current state", () => {
  const progress = runProgress({
    state: "auditing",
    iteration: 1,
    stages: [
      stage("ingesting", 0),
      stage("gating", 0),
      stage("drafting", 0),
      stage("conveying", 0),
      stage("auditing", 0),
      stage("drafting", 1),
      stage("conveying", 1),
    ],
  });
  expect(stepRows(progress).map((r) => [r.step, r.status, r.attempts.length, r.revision])).toEqual([
    ["created", "done", 0, ""],
    ["ingesting", "done", 1, ""],
    ["gating", "done", 1, ""],
    ["drafting", "done", 2, ""],
    ["conveying", "done", 2, ""],
    ["auditing", "now", 1, "revision 1 of 2"],
    ["rendering", "pending", 0, ""],
    ["completed", "pending", 0, ""],
  ]);
  const failed = runProgress({
    state: "failed",
    stages: [stage("ingesting", 0), stage("gating", 0, false, "model unreachable")],
  });
  expect(stepRows(failed).map((r) => r.status)).toEqual([
    "done",
    "done",
    "failed",
    "pending",
    "pending",
    "pending",
    "pending",
    "pending",
  ]);
  expect(stepRows(runProgress()).map((r) => r.status)).toEqual([
    "now",
    ...Array(7).fill("pending"),
  ]);
  expect(stepRows(runProgress({ state: "cancelled" }))[0]?.status).toBe("pending");
  const completed = stepRows(runProgress({ state: "completed", stages: [stage("rendering", 1)] }));
  expect(completed.at(-1)?.status).toBe("done");
  expect(completed.at(-2)?.status).toBe("done");
});

it("shows each step's state as a symbol and a word, and marks the current step", () => {
  render(
    <Steps
      progress={runProgress({
        state: "drafting",
        iteration: 1,
        stages: [stage("ingesting", 0), stage("gating", 0), stage("drafting", 0)],
      })}
    />,
  );
  const items = within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem");
  expect(items).toHaveLength(8);
  expect(items[1]).toHaveTextContent("✓Reading the sourcesdone");
  expect(items[3]).toHaveTextContent("●Draftingnow · revision 1 of 2");
  expect(items[3]).toHaveAttribute("aria-current", "step");
  expect(items[7]).toHaveTextContent("○Ready to reviewnot yet");
  expect(items[7]).not.toHaveAttribute("aria-current");
  expect(items[1]!.querySelector(".step-mark")).toHaveAttribute("aria-hidden", "true");
});

it("marks a failed step, and no current step once the report has ended", () => {
  render(
    <Steps
      progress={runProgress({
        state: "failed",
        stages: [stage("ingesting", 0), stage("gating", 0, false, "model unreachable")],
      })}
    />,
  );
  const items = screen.getAllByRole("listitem");
  expect(items[2]).toHaveTextContent("!Checking the value statementfailed");
  expect(items.some((li) => li.hasAttribute("aria-current"))).toBe(false);
});

it("lists each stage's duration, how often it ran and a failed stage's error under Details", () => {
  const unfinished = { ...stage("gating", 0, false, "model unreachable"), finished_at: "" };
  const { rerender } = render(
    <StageDetails
      progress={runProgress({
        state: "failed",
        stages: [stage("ingesting", 0), stage("drafting", 0), stage("drafting", 1), unfinished],
      })}
    />,
  );
  const lines = within(screen.getByRole("list", { name: "Stage details" })).getAllByRole(
    "listitem",
  );
  expect(lines.map((li) => li.textContent)).toEqual([
    "Reading the sources: 3.0 s",
    "Checking the value statement: model unreachable",
    "Drafting: 3.0 s · ran 2 times",
  ]);
  expect(lines[1]).toHaveAttribute("dir", "auto");
  rerender(<StageDetails progress={runProgress({ stages: undefined })} />);
  expect(screen.getByText("Nothing has started yet.")).toBeInTheDocument();
  rerender(
    <StageDetails
      progress={runProgress({ stages: [{ ...stage("ingesting", 0), finished_at: "" }] })}
    />,
  );
  expect(screen.getByRole("listitem")).toHaveTextContent(/^Reading the sources$/);
});
```

```diff
diff --git a/web/src/pages/run/RunPage.test.tsx b/web/src/pages/run/RunPage.test.tsx
index 5317127..053351a 100644
--- a/web/src/pages/run/RunPage.test.tsx
+++ b/web/src/pages/run/RunPage.test.tsx
@@ -3,7 +3,8 @@ import { http, HttpResponse } from "msw";
 import { setEventSourceFactory } from "../../api/events";
 import { POLL_MS } from "../../api/runs";
 import { FakeEventSource } from "../../test/fake-events";
-import { RUN_ID, runProgress, runTrace } from "../../test/fixtures";
+import { expectNoEngineWords } from "../../test/engine-words";
+import { project, reportJson, RUN_ID, runProgress, runTrace } from "../../test/fixtures";
 import { runRefetchInterval } from "../../test/poll";
 import { renderApp } from "../../test/render";
 import { server } from "../../test/server";
@@ -16,6 +17,16 @@ afterEach(() => setEventSourceFactory(undefined));
 
 const usage = { calls: 3, tokens_in: 4200, tokens_out: 900, by_role: {} };
 
+/** The step the page marks as in progress (aria-current="step"), checked by its name. */
+function currentStep(name: string): HTMLElement {
+  const step = screen
+    .getByRole("list", { name: "Steps" })
+    .querySelector<HTMLElement>('[aria-current="step"]');
+  expect(step?.querySelector(".step-name")).toHaveTextContent(name);
+  return step!;
+}
+const findCurrentStep = (name: string) => waitFor(() => currentStep(name));
+
 it("shows the live run, applies stream events and links to the review when done (test_terminal_event_closes_the_stream_and_links_to_review)", async () => {
   server.use(
     http.get(`*/api/runs/${RUN_ID}`, () =>
@@ -23,13 +34,13 @@ it("shows the live run, applies stream events and links to the review when done
     ),
   );
   renderApp(`/runs/${RUN_ID}`);
-  expect(await screen.findByRole("heading", { name: "Run progress" })).toBeInTheDocument();
-  expect(screen.getByText("Checking the value", { selector: ".badge" })).toBeInTheDocument();
+  expect(await screen.findByRole("heading", { name: "Writing the report" })).toBeInTheDocument();
+  expect(currentStep("Checking the value statement")).toBeInTheDocument();
   expect(screen.getByRole("status", { name: "Token usage" })).toHaveTextContent("3 model calls");
   expect(screen.getByRole("status", { name: "Token usage" })).toHaveTextContent("4,200 in");
   const source = FakeEventSource.last();
   source.emit("progress", runProgress({ state: "drafting", iteration: 0, usage }));
-  expect(await screen.findByText("Drafting", { selector: ".badge" })).toBeInTheDocument();
+  expect(await findCurrentStep("Drafting")).toBeInTheDocument();
   source.emit(
     "progress",
     runProgress({
@@ -44,9 +55,9 @@ it("shows the live run, applies stream events and links to the review when done
     "href",
     `/runs/${RUN_ID}/review`,
   );
-  expect(screen.getByText("Clean: every applicable rule passed.")).toBeInTheDocument();
+  expect(screen.getByText("Meets the standards.")).toBeInTheDocument();
   expect(source.closed).toBe(true);
-  expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
+  expect(screen.queryByRole("button", { name: "Stop writing…" })).not.toBeInTheDocument();
 });
 
 it("shows the gate's reasons for a rejected run with a way to start again", async () => {
@@ -75,7 +86,7 @@ it("shows the gate's reasons for a rejected run with a way to start again", asyn
   renderApp(`/runs/${RUN_ID}`);
   expect(await screen.findByText("The sources never mention Varna.")).toBeInTheDocument();
   expect(screen.getByText("Write about Burgas instead.")).toBeInTheDocument();
-  expect(screen.getByRole("link", { name: "Start a new run" })).toHaveAttribute(
+  expect(screen.getByRole("link", { name: "Try another statement" })).toHaveAttribute(
     "href",
     `/new?project=${runProgress().project_id}`,
   );
@@ -97,8 +108,10 @@ it("shows a failure and a cancelled run", async () => {
   );
   renderApp(`/runs/${RUN_ID}`);
   expect(
-    await screen.findByText("This run was cancelled before a report was produced."),
+    await screen.findByRole("heading", { name: "Stopped before the report was written." }),
   ).toBeInTheDocument();
+  // the failed run's page above and the cancelled run's both offer a new report
+  expect(screen.getAllByRole("link", { name: "Start a new report" })).toHaveLength(2);
 });
 
 it("cancels after a confirmation (test for the cancel path)", async () => {
@@ -111,14 +124,14 @@ it("cancels after a confirmation (test for the cancel path)", async () => {
     }),
   );
   const { user } = renderApp(`/runs/${RUN_ID}`);
-  await user.click(await screen.findByRole("button", { name: "Cancel run" }));
+  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
   await user.click(screen.getByRole("button", { name: "Keep going" }));
   expect(cancelled).toBe(false);
-  await user.click(screen.getByRole("button", { name: "Cancel run" }));
-  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel run" }));
+  await user.click(screen.getByRole("button", { name: "Stop writing…" }));
+  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop" }));
   await waitFor(() => expect(cancelled).toBe(true));
-  expect(await screen.findByText("Stopping after the current stage…")).toBeInTheDocument();
-  expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
+  expect(await screen.findByText("Stopping after the current step…")).toBeInTheDocument();
+  expect(screen.queryByRole("button", { name: "Stop writing…" })).not.toBeInTheDocument();
 });
 
 it("ends on a deleted event with the not-found message (test_deleted_event_shows_not_found)", async () => {
@@ -132,7 +145,7 @@ it("ends on a deleted event with the not-found message (test_deleted_event_shows
   );
   const { queryClient } = renderApp(`/runs/${RUN_ID}`);
   const invalidate = vi.spyOn(queryClient, "invalidateQueries");
-  await screen.findByText("Checking the value", { selector: ".badge" });
+  await findCurrentStep("Checking the value statement");
   deleted = true;
   FakeEventSource.last().emit("deleted", {});
   expect(await screen.findByRole("alert")).toHaveTextContent("not found");
@@ -144,7 +157,7 @@ it("polls when the stream gave up, and stops once the run is terminal", async ()
   let state: "gating" | "completed" = "gating";
   server.use(http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state }))));
   const { queryClient } = renderApp(`/runs/${RUN_ID}`);
-  await screen.findByText("Checking the value", { selector: ".badge" });
+  await findCurrentStep("Checking the value statement");
   expect(runRefetchInterval(queryClient, RUN_ID)).toBe(false); // the stream delivers updates
   act(() => FakeEventSource.last().fail());
   expect(
@@ -165,7 +178,7 @@ it("does not carry a stream failure over to another run", async () => {
     ),
   );
   const { router } = renderApp(`/runs/${RUN_ID}`);
-  await screen.findByText("Checking the value", { selector: ".badge" });
+  await findCurrentStep("Checking the value statement");
   act(() => FakeEventSource.last().fail());
   await screen.findByText("Live updates are off; checking every few seconds.");
   await act(() => router.navigate(`/runs/${other}`));
@@ -174,3 +187,96 @@ it("does not carry a stream failure over to another run", async () => {
   );
   await waitFor(() => expect(FakeEventSource.last().url).toContain(other));
 });
+
+it("leads back to the project, says it can be left, keeps the detail folded, and names the tab", async () => {
+  server.use(
+    http.get("*/api/projects", () => HttpResponse.json([project])),
+    http.get(`*/api/runs/${RUN_ID}`, () =>
+      HttpResponse.json(
+        runProgress({
+          state: "conveying",
+          iteration: 1,
+          usage,
+          stages: [
+            {
+              stage: "ingesting",
+              iteration: 0,
+              ok: true,
+              error: null,
+              output: null,
+              started_at: "2026-10-13T10:02:00Z",
+              finished_at: "2026-10-13T10:02:01Z",
+            },
+          ],
+        }),
+      ),
+    ),
+  );
+  renderApp(`/runs/${RUN_ID}`);
+  const main = screen.getByRole("main");
+  const crumb = await within(main).findByRole("navigation", { name: "Breadcrumb" });
+  expect(await within(crumb).findByRole("link", { name: project.name })).toHaveAttribute(
+    "href",
+    `/new?project=${project.id}`,
+  );
+  expect(currentStep("Editing for the reader")).toHaveTextContent("now · revision 1 of 2");
+  expect(
+    within(main).getByText(
+      "This usually takes a few minutes. You can leave this page; it keeps going.",
+    ),
+  ).toBeInTheDocument();
+  const details = within(main).getByText("Details").closest("details")!;
+  expect(details).not.toHaveAttribute("open");
+  expect(within(details).getByText("Reading the sources: 1.0 s")).toBeInTheDocument();
+  expect(within(details).getByRole("status", { name: "Token usage" })).toHaveTextContent(
+    "3 model calls",
+  );
+  await waitFor(() => expect(document.title).toBe(`Writing… – ${project.name}`));
+  expectNoEngineWords(main);
+});
+
+it("asks before it stops a report, in the reader's words", async () => {
+  server.use(
+    http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
+  );
+  const { user } = renderApp(`/runs/${RUN_ID}`);
+  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
+  const dialog = screen.getByRole("dialog", { name: "Stop this report?" });
+  expect(dialog).toHaveTextContent(
+    "It stops after the step in progress; no report will be produced.",
+  );
+  expect(within(dialog).getByRole("button", { name: "Keep going" })).toBeInTheDocument();
+  expect(within(dialog).getByRole("button", { name: "Stop" })).toHaveClass("danger");
+});
+
+it("ends with the outcome's heading, one way on, and the report's title on the tab", async () => {
+  server.use(
+    http.get(`*/api/runs/${RUN_ID}`, () =>
+      HttpResponse.json(runProgress({ state: "completed", status: "clean" })),
+    ),
+  );
+  renderApp(`/runs/${RUN_ID}`);
+  expect(await screen.findByRole("heading", { name: "Ready to review." })).toBeInTheDocument();
+  expect(screen.getByRole("link", { name: "Review the report" })).toHaveClass("primary");
+  expect(screen.queryByRole("button", { name: "Stop writing…" })).toBeNull();
+  await waitFor(() => expect(document.title).toBe(`✓ Ready to review – ${reportJson.title}`));
+  expect(screen.getAllByRole("listitem").at(-1)).toHaveAttribute("data-status", "done");
+});
+
+it("names a report that did not get written on the tab by its status", async () => {
+  server.use(
+    http.get("*/api/projects", () => HttpResponse.json([project])),
+    http.get(`*/api/runs/${RUN_ID}`, () =>
+      HttpResponse.json(runProgress({ state: "gate_rejected" })),
+    ),
+    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
+  );
+  renderApp(`/runs/${RUN_ID}`);
+  expect(
+    await screen.findByRole("heading", { name: "Not supported by the sources." }),
+  ).toBeInTheDocument();
+  await waitFor(() =>
+    expect(document.title).toBe(`Not supported by the sources – ${project.name}`),
+  );
+  expectNoEngineWords(screen.getByRole("main"));
+});
```

```diff
diff --git a/web/src/pages/run/RunOutcome.test.tsx b/web/src/pages/run/RunOutcome.test.tsx
index c1171b0..6576b91 100644
--- a/web/src/pages/run/RunOutcome.test.tsx
+++ b/web/src/pages/run/RunOutcome.test.tsx
@@ -3,7 +3,7 @@ import { http, HttpResponse } from "msw";
 import { setEventSourceFactory } from "../../api/events";
 import { POLL_MS } from "../../api/runs";
 import { FakeEventSource } from "../../test/fake-events";
-import { RUN_ID, runProgress, runTrace } from "../../test/fixtures";
+import { reportJson, RUN_ID, runProgress, runTrace } from "../../test/fixtures";
 import { runRefetchInterval } from "../../test/poll";
 import { renderApp } from "../../test/render";
 import { server } from "../../test/server";
@@ -27,19 +27,29 @@ function traceWithGate(gate: unknown) {
   );
 }
 
-it("says when a delivered report has findings open and surfaces an export failure", async () => {
+it("says how many standards a delivered report did not meet and surfaces an export failure", async () => {
+  server.use(
+    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
+      HttpResponse.json({
+        ...reportJson,
+        metadata: { ...reportJson.metadata, status: "findings_open", open_findings: ["a@1"] },
+      }),
+    ),
+  );
   renderTerminal({
     state: "completed",
     status: "findings_open",
     export_error: "pdf export failed",
   });
-  expect(await screen.findByText(/Delivered with findings open/)).toBeInTheDocument();
+  expect(
+    await screen.findByText("1 standard not met; they're listed under Standards."),
+  ).toBeInTheDocument();
   expect(screen.getByRole("alert")).toHaveTextContent("pdf export failed");
 });
 
 it("falls back to a generic message for a failed run without an error", async () => {
   renderTerminal({ state: "failed", error: null });
-  expect(await screen.findByRole("alert")).toHaveTextContent("The run failed.");
+  expect(await screen.findByRole("alert")).toHaveTextContent("No reason was recorded.");
 });
 
 it("shows a rejection without a suggested scope", async () => {
@@ -63,14 +73,14 @@ it("shows a trace failure for a rejected run inline and still offers a new run",
   );
   renderTerminal({ state: "gate_rejected" });
   expect(await screen.findByRole("alert")).toHaveTextContent("trace unavailable");
-  expect(screen.getByRole("link", { name: "Start a new run" })).toBeInTheDocument();
+  expect(screen.getByRole("link", { name: "Try another statement" })).toBeInTheDocument();
 });
 
 it("shows only the headline for a rejected run whose trace has no gate", async () => {
   traceWithGate(null);
   renderTerminal({ state: "gate_rejected" });
   expect(
-    await screen.findByText("The gate did not find the stated value in these sources."),
+    await screen.findByText("The value check didn't find this in the sources."),
   ).toBeInTheDocument();
   await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
 });
@@ -81,7 +91,7 @@ it("polls from the start without EventSource and shows the attempt number", asyn
   expect(
     await screen.findByText("Live updates are off; checking every few seconds."),
   ).toBeInTheDocument();
-  expect(screen.getByText(/attempt 2/)).toBeInTheDocument();
+  expect(screen.getByText(/Started 2 times/)).toBeInTheDocument();
   expect(FakeEventSource.instances).toHaveLength(0);
   expect(runRefetchInterval(queryClient, RUN_ID)).toBe(POLL_MS);
 });
@@ -104,16 +114,16 @@ it("shows a cancel failure inline and keeps the cancel button", async () => {
     ),
   );
   const { user } = renderApp(`/runs/${RUN_ID}`);
-  await user.click(await screen.findByRole("button", { name: "Cancel run" }));
-  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel run" }));
+  await user.click(await screen.findByRole("button", { name: "Stop writing…" }));
+  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop" }));
   expect(await screen.findByRole("alert")).toHaveTextContent("run is already finishing");
-  expect(screen.getByRole("button", { name: "Cancel run" })).toBeInTheDocument();
+  expect(screen.getByRole("button", { name: "Stop writing…" })).toBeInTheDocument();
 });
 
 it("says when a cancel arrived too late to stop a delivered report", async () => {
   renderTerminal({ state: "completed", status: "clean", cancel_requested: true });
   expect(
-    await screen.findByText(/A cancel was requested, but the run had already finished/),
+    await screen.findByText(/A stop was asked for, but the report had already finished/),
   ).toBeInTheDocument();
   expect(screen.getByRole("link", { name: "Review the report" })).toBeInTheDocument();
 });
```

`StateBadge` goes with its test:

```diff
diff --git a/web/src/components/primitives.test.tsx b/web/src/components/primitives.test.tsx
index d2adebe..12f7183 100644
--- a/web/src/components/primitives.test.tsx
+++ b/web/src/components/primitives.test.tsx
@@ -5,7 +5,6 @@ import { renderApp } from "../test/render";
 import { ErrorMessage, messageOf } from "./ErrorMessage";
 import { Loading } from "./Loading";
 import { RouteError } from "./RouteError";
-import { StateBadge } from "./StateBadge";
 
 it("links the not-found page back to the new report screen", async () => {
   renderApp("/nope");
@@ -30,12 +29,6 @@ it("announces loading with a polite status", () => {
   expect(screen.getByText("Loading runs…")).toBeInTheDocument();
 });
 
-it("labels a run state with its human name and a state class", () => {
-  render(<StateBadge state="gate_rejected" />);
-  const badge = screen.getByText("Value not supported");
-  expect(badge).toHaveClass("badge", "state-gate_rejected");
-});
-
 it("replaces a page that throws, with a way back", async () => {
   vi.spyOn(console, "error").mockImplementation(() => {});
   const Boom = () => {
```

A completed run's page reads its report's title (R-M18-16, R-M18-20):

```diff
diff --git a/web/src/test/server.ts b/web/src/test/server.ts
index 2206f0f..6521db6 100644
--- a/web/src/test/server.ts
+++ b/web/src/test/server.ts
@@ -1,10 +1,12 @@
 import { http, HttpResponse } from "msw";
 import { setupServer } from "msw/node";
-import { info } from "./fixtures";
+import { info, reportJson } from "./fixtures";
 
 // Every page renders the layout, which asks who is signed in and which version answers, and
-// the sidebar, which lists the projects (none, unless a test serves some).
+// the sidebar, which lists the projects (none, unless a test serves some). A completed run's
+// page reads its report's title for the browser tab (M18 spec §3.4).
 export const server = setupServer(
   http.get("*/api/system/info", () => HttpResponse.json(info)),
   http.get("*/api/projects", () => HttpResponse.json([])),
+  http.get("*/api/runs/:runId/exports/report.json", () => HttpResponse.json(reportJson)),
 );
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/pages/run src/components/primitives.test.tsx`
Expected: FAIL: `StageTimeline.test.tsx` imports no `stepRows`, `Steps`, `StageDetails`; the page tests find no "Writing the report" heading, no `aria-current="step"`, no "Stop writing…" button, no "Ready to review." heading.

- [ ] **Step 3: The steps and the Details lines (R-M18-24)**

Replace `web/src/pages/run/StageTimeline.tsx`:

```tsx
import type { RunProgress, StageResult } from "../../api/types";
import { durationBetween, formatDuration, isTerminal, STAGES, type Stage } from "../../lib/format";
import {
  plural,
  PROGRESS_STEPS,
  REVISED_STEPS,
  STEP_LABEL,
  type ProgressStep,
} from "../../lib/words";

export type StepStatus = "done" | "now" | "failed" | "pending";

/** M18 spec §5.3: a step's state as a symbol and a word, never colour alone. */
export const STEP_MARK: Record<StepStatus, { symbol: string; word: string }> = {
  done: { symbol: "✓", word: "done" },
  now: { symbol: "●", word: "now" },
  failed: { symbol: "!", word: "failed" },
  pending: { symbol: "○", word: "not yet" },
};

export type StepRow = {
  step: ProgressStep;
  label: string;
  status: StepStatus;
  /** "revision 1 of 2" on the step in progress of a revision (§4.3); empty otherwise */
  revision: string;
  attempts: StageResult[];
};

function stageStatus(progress: RunProgress, stage: Stage, attempts: StageResult[]): StepStatus {
  const last = attempts.at(-1);
  if (progress.state === stage) return "now";
  if (last) return last.ok ? "done" : "failed";
  return "pending";
}

/** One row per step (spec §4.3): waiting to start, the six stages, ready to review. A stage is
 * now when it is the run's state; done when its last attempt succeeded; failed when its last
 * attempt failed; not yet otherwise. */
export function stepRows(progress: RunProgress): StepRow[] {
  const stages = progress.stages ?? [];
  return PROGRESS_STEPS.map((step) => {
    const attempts = stages.filter((s) => s.stage === step);
    let status: StepStatus;
    if (step === "created") {
      status = progress.state === "created" ? "now" : stages.length > 0 ? "done" : "pending";
    } else if (step === "completed") {
      status = progress.state === "completed" ? "done" : "pending";
    } else {
      status = stageStatus(progress, step, attempts);
    }
    const revision =
      status === "now" && progress.iteration > 0 && REVISED_STEPS.has(step)
        ? `revision ${progress.iteration} of ${progress.max_iterations}`
        : "";
    return { step, label: STEP_LABEL[step], status, revision, attempts };
  });
}

/** The ordered steps; the one in progress carries aria-current="step". */
export function Steps({ progress }: { progress: RunProgress }) {
  const live = !isTerminal(progress.state);
  return (
    <ol aria-label="Steps" className="steps">
      {stepRows(progress).map((row) => (
        <li
          key={row.step}
          data-status={row.status}
          aria-current={live && row.status === "now" ? "step" : undefined}
        >
          <span className="step-mark" aria-hidden="true">
            {STEP_MARK[row.status].symbol}
          </span>
          <span className="step-name">{row.label}</span>
          <span className="step-state">
            {STEP_MARK[row.status].word}
            {row.revision ? ` · ${row.revision}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

function stageLine(stage: Stage, attempts: StageResult[]): string {
  const last = attempts.at(-1)!;
  const ms = durationBetween(last.started_at, last.finished_at);
  const parts = [ms === null ? "" : formatDuration(ms)];
  if (attempts.length > 1) parts.push(`ran ${plural(attempts.length, "time")}`);
  if (!last.ok && last.error) parts.push(last.error);
  const text = parts.filter(Boolean).join(" · ");
  return text ? `${STEP_LABEL[stage]}: ${text}` : STEP_LABEL[stage];
}

/** The Details fold's stage lines (before M18 the timeline's text): duration, how many times a
 * stage ran, and a failed stage's error. */
export function StageDetails({ progress }: { progress: RunProgress }) {
  const stages = progress.stages ?? [];
  const lines = STAGES.map((stage) => [stage, stages.filter((s) => s.stage === stage)] as const)
    .filter(([, attempts]) => attempts.length > 0)
    .map(([stage, attempts]) => stageLine(stage, attempts));
  if (lines.length === 0) return <p className="muted">Nothing has started yet.</p>;
  return (
    <ul aria-label="Stage details" className="stage-details">
      {lines.map((line) => (
        <li key={line} dir="auto">
          {line}
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Stop, the outcomes, the page**

Replace `web/src/pages/run/CancelRun.tsx`:

```tsx
import { useState } from "react";
import { useCancelRun } from "../../api/runs";
import type { RunProgress } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorMessage } from "../../components/ErrorMessage";

/** M18 spec §5.3: Stop writing…, after a confirmation; the run stops at its next stage. */
export function CancelRun({ runId, progress }: { runId: string; progress: RunProgress }) {
  const cancel = useCancelRun(runId);
  const [open, setOpen] = useState(false);
  if (progress.cancel_requested) {
    return (
      <p role="status" className="muted">
        Stopping after the current step…
      </p>
    );
  }
  return (
    <>
      <button type="button" className="danger" onClick={() => setOpen(true)}>
        Stop writing…
      </button>
      {cancel.error ? <ErrorMessage error={cancel.error} /> : null}
      <ConfirmDialog
        open={open}
        title="Stop this report?"
        confirmLabel="Stop"
        danger
        busy={cancel.isPending}
        onConfirm={() => cancel.mutate(undefined, { onSettled: () => setOpen(false) })}
        onCancel={() => setOpen(false)}
      >
        <p>It stops after the step in progress; no report will be produced.</p>
      </ConfirmDialog>
    </>
  );
}
```

Replace `web/src/pages/run/RunOutcome.tsx`:

```tsx
import { Link } from "react-router";
import { useTrace } from "../../api/reports";
import type { RunProgress } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { plural } from "../../lib/words";

function GateReasons({ runId }: { runId: string }) {
  const trace = useTrace(runId);
  const gate = trace.data?.summary.gate;
  if (trace.error) return <ErrorMessage error={trace.error} />;
  if (!gate) return null;
  return (
    <div>
      <ul>
        {gate.reasons.map((reason, i) => (
          <li key={i} dir="auto">
            {reason}
          </li>
        ))}
      </ul>
      {gate.suggested_scope ? (
        <p>
          <strong>Suggested scope:</strong> <span dir="auto">{gate.suggested_scope}</span>
        </p>
      ) : null}
    </div>
  );
}

/** M18 spec §5.3: what a finished run means for the analyst, and the one way on. */
export function outcomeHeading(progress: RunProgress): string | null {
  switch (progress.state) {
    case "completed":
      return "Ready to review.";
    case "gate_rejected":
      return "Not supported by the sources.";
    case "failed":
      return "This report couldn't be written.";
    case "cancelled":
      return "Stopped before the report was written.";
    default:
      return null;
  }
}

function completedText(progress: RunProgress, open: number | undefined): string {
  if (progress.status === "clean") return "Meets the standards.";
  if (open === undefined) return "Some standards are not met; they're listed under Standards.";
  if (open > 0) return `${plural(open, "standard")} not met; they're listed under Standards.`;
  return "Checked in part: it was delivered without a full check.";
}

/** `openFindings`: the delivered report's open rules, once its report.json has loaded. */
export function RunOutcome({
  progress,
  openFindings,
}: {
  progress: RunProgress;
  openFindings?: number;
}) {
  const again = `/new?project=${progress.project_id}`;
  switch (progress.state) {
    case "completed":
      return (
        <section aria-label="Outcome" className="outcome">
          <p>{completedText(progress, openFindings)}</p>
          {progress.cancel_requested ? (
            <p className="muted">
              A stop was asked for, but the report had already finished its last step, so it was
              delivered.
            </p>
          ) : null}
          {progress.export_error ? <ErrorMessage error={new Error(progress.export_error)} /> : null}
          <Link to={`/runs/${progress.run_id}/review`} className="button primary">
            Review the report
          </Link>
        </section>
      );
    case "gate_rejected":
      return (
        <section aria-label="Outcome" className="outcome">
          <p>The value check didn&apos;t find this in the sources.</p>
          <GateReasons runId={progress.run_id} />
          <Link to={again} className="button">
            Try another statement
          </Link>
        </section>
      );
    case "failed":
      return (
        <section aria-label="Outcome" className="outcome">
          <ErrorMessage error={new Error(progress.error ?? "No reason was recorded.")} />
          <Link to={again} className="button">
            Start a new report
          </Link>
        </section>
      );
    case "cancelled":
      return (
        <section aria-label="Outcome" className="outcome">
          <Link to={again} className="button">
            Start a new report
          </Link>
        </section>
      );
    default:
      return null;
  }
}
```

Replace `web/src/pages/run/RunPage.tsx`:

```tsx
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";
import { liveUpdatesAvailable, useRunEvents } from "../../api/events";
import { useProjects } from "../../api/projects";
import { useReportJson } from "../../api/reports";
import { useRun } from "../../api/runs";
import type { RunProgress } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useActiveProject, useDocumentTitle } from "../../components/frame";
import { Loading } from "../../components/Loading";
import { isTerminal } from "../../lib/format";
import { fromProgress, runStatus } from "../../lib/status";
import { CancelRun } from "./CancelRun";
import { outcomeHeading, RunOutcome } from "./RunOutcome";
import { StageDetails, Steps } from "./StageTimeline";
import { UsageSummary } from "./UsageSummary";

/** M18 spec §3.4: the tab names what the report is waiting for. */
function tabTitle(progress: RunProgress | undefined, project: string, report: string | undefined) {
  if (!progress) return null;
  if (!isTerminal(progress.state)) return `Writing… – ${project}`;
  if (progress.state === "completed") return `✓ Ready to review – ${report ?? project}`;
  const status = runStatus(fromProgress(progress));
  return `${status.text[0]!.toUpperCase()}${status.text.slice(1)} – ${project}`;
}

/** M18 spec §5.3: the steps over the event stream (polling when there is none), the Details
 * fold, Stop writing…, and the outcome once the run ends. */
export function RunPage() {
  const { runId = "" } = useParams();
  const [failedRun, setFailedRun] = useState<string | null>(null);
  const streamFailed = failedRun === runId; // a failure belongs to the run it happened on
  const live = liveUpdatesAvailable() && !streamFailed;
  const run = useRun(runId, live);
  const progress = run.data;
  useActiveProject(progress?.project_id ?? null);
  const projects = useProjects();
  const project = (projects.data ?? []).find((p) => p.id === progress?.project_id);
  const report = useReportJson(runId, progress?.state === "completed");
  useDocumentTitle(tabTitle(progress, project?.name ?? "Corelata", report.data?.title));
  const onStreamFailed = useCallback(() => setFailedRun(runId), [runId]);
  useRunEvents(
    runId,
    progress !== undefined && !isTerminal(progress.state) && live,
    onStreamFailed,
  );

  if (run.isPending) return <Loading what="Loading the report's progress" />;
  if (run.error) return <ErrorMessage error={run.error} />;
  if (!progress) return null;
  const done = isTerminal(progress.state);
  return (
    <article className="writing">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to={`/new?project=${progress.project_id}`}>{project?.name ?? "Project"}</Link>
      </nav>
      <h1>{done ? outcomeHeading(progress) : "Writing the report"}</h1>
      <Steps progress={progress} />
      {done ? null : (
        <p className="muted">
          This usually takes a few minutes. You can leave this page; it keeps going.
        </p>
      )}
      {!live && !done ? (
        <p className="muted">Live updates are off; checking every few seconds.</p>
      ) : null}
      {done ? (
        <RunOutcome progress={progress} openFindings={report.data?.metadata.open_findings.length} />
      ) : null}
      <details className="details">
        <summary>Details</summary>
        <StageDetails progress={progress} />
        {progress.attempts > 1 ? (
          <p className="muted">
            Started {progress.attempts} times: an earlier try stopped and the report started over.
          </p>
        ) : null}
        <UsageSummary usage={progress.usage} />
      </details>
      {done ? null : <CancelRun runId={runId} progress={progress} />}
    </article>
  );
}
```

`git rm web/src/components/StateBadge.tsx`. Replace `web/src/styles/run.css`:

```css
/* Writing the report (spec §5.3). A step's state is its symbol and word; the colour only
   repeats it. */
.writing {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-width: 48rem;
}

.writing > h1 {
  margin: 0;
}

.breadcrumb {
  font-size: var(--text-sm);
}

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-1);
}

.steps li {
  display: grid;
  grid-template-columns: 1.5rem minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: baseline;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-1);
}

.steps li[data-status="now"] {
  background: var(--selected);
  font-weight: 600;
}

.steps li[data-status="done"] .step-mark {
  color: var(--ok);
}

.steps li[data-status="now"] .step-mark {
  color: var(--accent);
}

.steps li[data-status="failed"] .step-mark,
.steps li[data-status="failed"] .step-state {
  color: var(--danger);
}

.steps li[data-status="pending"] {
  color: var(--text-muted);
}

.step-state {
  font-size: var(--text-sm);
}

.outcome {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
}

.outcome p {
  margin: 0;
}

.details > summary {
  margin-bottom: var(--space-2);
}

.stage-details {
  margin: 0 0 var(--space-2);
  padding-inline-start: var(--space-5);
}
```

- [ ] **Step 5: Run the tests, lint and build**

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: clean; 357 passed in 50 files, coverage at least 95%. The pinned tests keep their assertions: "polls when the stream gave up, and stops once the run is terminal" (`POLL_MS`, then `false`), "does not carry a stream failure over to another run", "ends on a deleted event…", "polls from the start without EventSource…".

- [ ] **Step 6: Commit**

```bash
cat > "$SCRATCH/m18-task6-commit.txt" <<'EOF'
feat(web): Writing the report, steps as symbols and words, Details, Stop writing (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/src/pages/run web/src/components/primitives.test.tsx web/src/styles/run.css web/src/test/server.ts
git -C "$REPO" commit -F "$SCRATCH/m18-task6-commit.txt"
```

(`git rm` in Step 4 staged the deletion of `StateBadge.tsx`.)

---

### Task 7: Review: the header and banner, the Download menu, the tabs, the frame's theme (spec §5.4, §5.5)

**Files:**
- Create: `web/src/pages/review/ReviewBanner.tsx`, `ReviewBanner.test.tsx`, `frameTheme.test.tsx`
- Modify: `web/src/pages/review/frameBridge.ts`, `ReportFrame.tsx`, `ReviewPage.tsx`, `ReviewActions.tsx`, `AuditTab.tsx`, `ProvenanceTab.tsx`, `ProcessTab.tsx`, `SourcesTab.tsx` and the tests `ReviewPage.test.tsx`, `ReviewActions.test.tsx`, `AuditTab.test.tsx`, `ProvenanceTab.test.tsx`, `ProcessTab.test.tsx`, `SourcesTab.test.tsx`; `web/src/lib/status.ts`, `status.test.ts`, `words.ts`, `words.test.ts`, `format.ts`, `format.test.ts`; `web/src/pages/new/NewRunPage.test.tsx`; `web/src/test/engine-words.ts`; `web/src/styles/review.css`

**Interfaces:**
- Consumes: Task 1's `useTheme`; Task 2's `Menu`, `StatusText`; Task 4's `VERDICT`, `CLAIM_KIND`, `citedByText`, `degradationText`, `plural`, `STEP_LABEL`, `reportStatusText`, `useActiveProject`, `useDocumentTitle`; Task 5's `expectNoEngineWords`.
- Produces: `HostToFrame` gains `{type: "corelata:theme"; theme: "light" | "dark"}`; `installFrameBridge(doc, post, listen, css, nonce, theme = "")`; `bridgeScript(nonce?, theme?)`; `withBridge(html, nonce?, theme?)`; `HIGHLIGHT_CSS` with the two theme classes; `ReviewBanner({review, open, degradations, onShowStandards})`, `revisionOutcome(review)`; `downloads(runId)`; `reportStatus(status, open)` in `lib/status.ts`; `severityText(severity)` in `lib/words.ts`; `stageName(stage)` in `ProcessTab.tsx`; `visiblePrimaryButtons(root)` in `test/engine-words.ts`; names on screen: "Breadcrumb", "Where the review stands" (the banner, `role="status"`), "Accept", "Return with note…", "Download" (menu), "Claims", "Standards", "Evidence for claim <id>", "Not met", "Met and not applicable", "Advisory", "Why", "History".

- [ ] **Step 1: Write the failing tests**

Create `web/src/pages/review/frameTheme.test.tsx` (`frameBridge.test.ts` and `ReportFrame.test.tsx` stay as they are, R-M18-10):

```tsx
import { act, render, screen } from "@testing-library/react";
import { reportHtml } from "../../test/fixtures";
import { resetThemeForTests, setThemeChoice } from "../../theme/theme";
import {
  bridgeScript,
  HIGHLIGHT_CSS,
  installFrameBridge,
  withBridge,
  type HostToFrame,
} from "./frameBridge";
import { ReportFrame } from "./ReportFrame";

// M18 spec §5.5, R-M18-2, R-M18-10: the report follows the app's theme, not the computer's.

beforeEach(() => {
  localStorage.clear();
  resetThemeForTests();
});

function install(theme?: string) {
  const doc = new DOMParser().parseFromString(reportHtml, "text/html");
  let handler: ((message: HostToFrame) => void) | undefined;
  installFrameBridge(
    doc,
    () => {},
    (h) => (handler = h),
    HIGHLIGHT_CSS,
    "n",
    theme,
  );
  return { root: doc.documentElement, send: (m: unknown) => handler!(m as HostToFrame) };
}

it("styles the report's colour scheme by a class the bridge sets, inside the nonce's style", () => {
  expect(HIGHLIGHT_CSS).toContain(":root.corelata-theme-light { color-scheme: light; }");
  expect(HIGHLIGHT_CSS).toContain(":root.corelata-theme-dark { color-scheme: dark; }");
  const { root, send } = install("dark");
  expect(root.className).toBe("corelata-theme-dark"); // from the first paint
  send({ type: "corelata:theme", theme: "light" });
  expect(root.className).toBe("corelata-theme-light");
  send({ type: "corelata:theme", theme: "purple" });
  expect(root.className).toBe("corelata-theme-light"); // anything else is ignored
  expect(install().root.className).toBe(""); // no theme given: the report's own rule applies
});

it("builds the frame in a given theme, and leaves the document as before without one", () => {
  expect(bridgeScript("n", "dark")).toContain(
    `${JSON.stringify(HIGHLIGHT_CSS)}, "n", "dark");</script>`,
  );
  expect(withBridge(reportHtml, "n", "light")).toContain(`"n", "light");</script>`);
  expect(withBridge(reportHtml, "n")).toContain(`, "n");</script>`);
});

function frame(): HTMLIFrameElement {
  return screen.getByTitle("Report") as HTMLIFrameElement;
}

function ready() {
  const event = new MessageEvent("message", { data: { type: "corelata:ready" } });
  Object.defineProperty(event, "source", { value: frame().contentWindow });
  act(() => {
    window.dispatchEvent(event);
  });
}

const themeMessages = (post: { mock: { calls: unknown[][] } }) =>
  post.mock.calls.map(([m]) => m).filter((m) => (m as HostToFrame).type === "corelata:theme");

it("opens the frame in the app's theme and tells it when the theme changes", () => {
  setThemeChoice("dark");
  render(<ReportFrame html={reportHtml} selectedClaim={null} onSelectClaim={() => {}} />);
  expect(frame().getAttribute("srcdoc")).toContain('"dark");</script>');
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  ready();
  expect(themeMessages(post)).toEqual([]); // it already shows the dark theme
  act(() => setThemeChoice("light"));
  expect(themeMessages(post)).toEqual([{ type: "corelata:theme", theme: "light" }]);
  expect(frame().getAttribute("srcdoc")).toContain('"dark");</script>'); // not rebuilt
});

it("tells a frame that reloaded after a change which theme to show", () => {
  setThemeChoice("light");
  const { rerender } = render(
    <ReportFrame html={reportHtml} selectedClaim={null} onSelectClaim={() => {}} />,
  );
  const post = vi.spyOn(frame().contentWindow!, "postMessage");
  ready();
  act(() => setThemeChoice("dark"));
  rerender(
    <ReportFrame html={reportHtml + "<!-- v2 -->"} selectedClaim={null} onSelectClaim={() => {}} />,
  );
  ready(); // the new document was built in the first theme, light
  expect(themeMessages(post)).toEqual([
    { type: "corelata:theme", theme: "dark" },
    { type: "corelata:theme", theme: "dark" },
  ]);
});
```

Create `web/src/pages/review/ReviewBanner.test.tsx`:

```tsx
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ReviewState } from "../../api/types";
import { AUDIT_INCOMPLETE } from "../../test/fixtures";
import { ReviewBanner } from "./ReviewBanner";

const AT = "2026-10-20T10:00:00Z";
const REVISED = "77777777-7777-7777-7777-777777777777";

function show(
  props: Partial<Parameters<typeof ReviewBanner>[0]> & { review?: ReviewState | null } = {},
) {
  const onShowStandards = vi.fn();
  const element = (
    <ReviewBanner
      review={props.review ?? null}
      open={props.open ?? 0}
      degradations={props.degradations ?? []}
      onShowStandards={onShowStandards}
    />
  );
  render(<RouterProvider router={createMemoryRouter([{ path: "/", element }])} />);
  return {
    banner: screen.getByRole("status", { name: "Where the review stands" }),
    onShowStandards,
  };
}

const returned = (child_state: ReviewState["child_state"] = null): ReviewState => ({
  decision: "returned",
  at: AT,
  actor: "ana",
  child_run_id: REVISED,
  child_state,
  child_error: null,
  note: "n",
});

it("says a clean report is ready", () => {
  expect(show().banner).toHaveTextContent(
    "Ready to review. Every standard that could be checked was met.",
  );
});

it("counts the standards not met and opens them", async () => {
  const { banner, onShowStandards } = show({ open: 2 });
  expect(banner).toHaveTextContent("Ready to review. 2 standards not met.");
  await userEvent.setup().click(within(banner).getByRole("button", { name: "Show them" }));
  expect(onShowStandards).toHaveBeenCalled();
});

it("says what was skipped, keeps the engine's error under Details, and shows an unknown line as it is", () => {
  const { banner } = show({
    degradations: [
      "conveyance skipped after 1 attempt: conveyor: bad JSON",
      AUDIT_INCOMPLETE,
      "new",
    ],
  });
  expect(banner).toHaveTextContent(
    "Delivered without a full check. Editing for the reader was skipped after 1 attempt. " +
      "The standards check didn't finish after 2 attempts. new",
  );
  const details = within(banner).getAllByRole("listitem");
  expect(details.map((li) => li.textContent)).toEqual([
    "conveyor: bad JSON",
    AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2),
  ]);
});

it("names who accepted and when, or only when", () => {
  const accepted: ReviewState = { decision: "accepted", at: AT, actor: "ana" };
  const when = new Date(AT).toLocaleString();
  expect(show({ review: accepted, open: 3 }).banner).toHaveTextContent(
    `Accepted by ana on ${when}.`,
  );
  cleanup();
  expect(show({ review: { ...accepted, actor: null } }).banner).toHaveTextContent(
    `Accepted on ${when}.`,
  );
});

it("says a returned report's revision is being written, or links to the written one", () => {
  const live = show({ review: returned() }).banner;
  expect(live).toHaveTextContent("Returned with a note. The revised report is being written.");
  expect(within(live).getByRole("link", { name: "Open the revised report" })).toHaveAttribute(
    "href",
    `/runs/${REVISED}`,
  );
  cleanup();
  const done = show({ review: returned("completed") }).banner;
  expect(done).toHaveTextContent(/^Returned with a note\.Open the revised report$/);
  cleanup();
  const making = show({ review: { ...returned(), child_run_id: null } }).banner;
  expect(within(making).queryByRole("link")).toBeNull(); // the revision is still being made
});

it("says how a revision that produced no report ended", () => {
  const failed = show({ review: { ...returned("failed"), child_error: "model down" } }).banner;
  expect(failed).toHaveTextContent(
    "Returned with a note. The revised report couldn't be written: model down. Return the report again or accept it.",
  );
});
```

The pinned review tests with the new names (the banner replaces the "Review decision" badge and the "Rerun outcome" note; their assertions stay):

```diff
diff --git a/web/src/pages/review/ReviewActions.test.tsx b/web/src/pages/review/ReviewActions.test.tsx
index 1ad82e6..0dc6812 100644
--- a/web/src/pages/review/ReviewActions.test.tsx
+++ b/web/src/pages/review/ReviewActions.test.tsx
@@ -7,6 +7,11 @@ import { runRefetchInterval } from "../../test/poll";
 import { renderApp } from "../../test/render";
 import { server } from "../../test/server";
 
+const BANNER = "Where the review stands";
+const banner = () => screen.getByRole("status", { name: BANNER });
+/** The banner's sentence once it says `text` (it is on the page from the first render). */
+const expectBanner = (text: string) => waitFor(() => expect(banner()).toHaveTextContent(text));
+
 function serveCompleted(overrides: Parameters<typeof runProgress>[0] = {}) {
   server.use(
     http.get(`*/api/runs/${RUN_ID}`, () =>
@@ -23,27 +28,21 @@ function serveCompleted(overrides: Parameters<typeof runProgress>[0] = {}) {
   );
 }
 
-it("offers the downloads", async () => {
+it("offers the four downloads in a menu, with plain names (M18 spec §5.4)", async () => {
   serveCompleted();
-  renderApp(`/runs/${RUN_ID}/review`);
-  const downloads = await screen.findByRole("group", { name: "Download" });
-  expect(screen.getByRole("link", { name: "DOCX" })).toHaveAttribute(
-    "href",
-    `/api/runs/${RUN_ID}/report?format=docx&download=true`,
-  );
-  expect(screen.getByRole("link", { name: "Markdown" })).toHaveAttribute(
-    "href",
-    `/api/runs/${RUN_ID}/report?format=md&download=true`,
-  );
-  expect(screen.getByRole("link", { name: "HTML" })).toHaveAttribute(
-    "href",
-    `/api/runs/${RUN_ID}/report?format=html&download=true`,
-  );
-  expect(screen.getByRole("link", { name: "Trace JSON" })).toHaveAttribute(
-    "href",
-    `/api/runs/${RUN_ID}/exports/trace.json`,
-  );
-  expect(downloads).toBeInTheDocument();
+  const { user } = renderApp(`/runs/${RUN_ID}/review`);
+  await user.click(await screen.findByRole("button", { name: "Download" }));
+  const menu = screen.getByRole("menu", { name: "Download" });
+  const items = within(menu).getAllByRole("menuitem");
+  expect(items.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
+    ["Word document (DOCX)", `/api/runs/${RUN_ID}/report?format=docx&download=true`],
+    ["Markdown", `/api/runs/${RUN_ID}/report?format=md&download=true`],
+    ["Web page (HTML)", `/api/runs/${RUN_ID}/report?format=html&download=true`],
+    ["Trace (JSON)", `/api/runs/${RUN_ID}/exports/trace.json`],
+  ]);
+  expect(items[0]).toHaveFocus(); // Coglossa's Menu: the first item takes focus
+  await user.keyboard("{Escape}");
+  expect(screen.queryByRole("menu")).toBeNull();
 });
 
 const accepted = {
@@ -83,23 +82,19 @@ it("accepts, then shows the server's decision and disables both actions (test_ac
   );
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
   await user.click(await screen.findByRole("button", { name: "Accept" }));
-  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
-    "Accepted",
-  );
+  await expectBanner("Accepted");
   expect(posted).toEqual({ action: "accept", note: "" });
   expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
-  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
+  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
 });
 
 it("a reload shows an accepted run as decided", async () => {
   serveCompleted({ review: accepted });
   renderApp(`/runs/${RUN_ID}/review`);
-  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
-    "Accepted",
-  );
+  await expectBanner("Accepted");
   expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
-  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
-  expect(screen.queryByRole("link", { name: "Open the rerun" })).not.toBeInTheDocument();
+  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
+  expect(screen.queryByRole("link", { name: "Open the revised report" })).not.toBeInTheDocument();
 });
 
 it("a returned run shows the decision and links to the rerun", async () => {
@@ -112,10 +107,8 @@ it("a returned run shows the decision and links to the rerun", async () => {
     },
   });
   renderApp(`/runs/${RUN_ID}/review`);
-  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
-    "Returned",
-  );
-  expect(screen.getByRole("link", { name: "Open the rerun" })).toHaveAttribute(
+  await expectBanner("Returned");
+  expect(screen.getByRole("link", { name: "Open the revised report" })).toHaveAttribute(
     "href",
     "/runs/77777777-7777-7777-7777-777777777777",
   );
@@ -150,7 +143,7 @@ it("shows a failed return inside the open dialog and keeps the note", async () =
     ),
   );
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "Fix it");
   await user.click(screen.getByRole("button", { name: "Return" }));
   const dialog = screen.getByRole("dialog");
@@ -160,14 +153,14 @@ it("shows a failed return inside the open dialog and keeps the note", async () =
   expect(dialog).toHaveAttribute("open");
   expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("Fix it");
   await user.click(screen.getByRole("button", { name: "Cancel" }));
-  await user.click(screen.getByRole("button", { name: "Return with note" }));
+  await user.click(screen.getByRole("button", { name: "Return with note…" }));
   expect(screen.queryByRole("alert")).not.toBeInTheDocument();
 });
 
 it("keeps Return disabled for a whitespace-only note", async () => {
   serveCompleted();
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "   ");
   expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
   expect(screen.getByText("A note is required.")).toBeInTheDocument();
@@ -188,11 +181,11 @@ it("returns with a note and opens the child run (test_return_requires_a_note_and
     http.get(`*/api/runs/${child.run_id}`, () => HttpResponse.json(child)),
   );
   const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   const dialog = await screen.findByRole("dialog", { name: "Return the report to the writer" });
   const send = screen.getByRole("button", { name: "Return" });
   expect(send).toBeDisabled();
-  expect(dialog).toHaveTextContent("The note becomes writer guidance for the new run.");
+  expect(dialog).toHaveTextContent("The note becomes guidance for the revised report.");
   await user.type(
     screen.getByRole("textbox", { name: "Note for the writer" }),
     "Add the 2027 date",
@@ -216,7 +209,7 @@ it("keeps the note through a failed return and clears it after one that succeeds
     }),
   );
   const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   const note = screen.getByRole("textbox", { name: "Note for the writer" });
   await user.type(note, "Add the 2027 date");
   await user.click(screen.getByRole("button", { name: "Return" }));
@@ -231,7 +224,7 @@ it("keeps the note through a failed return and clears it after one that succeeds
     { action: "return", note: "Add the 2027 date" },
   ]);
   expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}/review`);
-  await user.click(screen.getByRole("button", { name: "Return with note" }));
+  await user.click(screen.getByRole("button", { name: "Return with note…" }));
   expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("");
 });
 
@@ -253,35 +246,33 @@ function returned(overrides: Partial<ReviewState> = {}): ReviewState {
 it.each([
   [
     { child_state: "failed" as const, child_error: "could not queue the run: connection refused" },
-    "The rerun failed: could not queue the run: connection refused. Return the report again or accept it.",
+    "The revised report couldn't be written: could not queue the run: connection refused. Return the report again or accept it.",
   ],
   [
     { child_state: "failed" as const },
-    "The rerun failed: no reason was recorded. Return the report again or accept it.",
+    "The revised report couldn't be written: no reason was recorded. Return the report again or accept it.",
   ],
   [
     { child_state: "cancelled" as const },
-    "The rerun was cancelled; return the report again or accept it.",
+    "The revised report was stopped; return the report again or accept it.",
   ],
   [
     { child_state: "gate_rejected" as const },
-    "The rerun stopped at the gate (value not supported); return the report again or accept it.",
+    "The revised report stopped at the value check (not supported by the sources); return the report again or accept it.",
   ],
 ])(
   "a return whose rerun ended without a report offers both actions again (%o)",
   async (fate, says) => {
     serveCompleted({ review: returned(fate) });
     renderApp(`/runs/${RUN_ID}/review`);
-    expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
-      "Returned",
-    );
-    expect(screen.getByRole("note", { name: "Rerun outcome" })).toHaveTextContent(says);
-    expect(screen.getByRole("link", { name: "Open the rerun" })).toHaveAttribute(
+    await expectBanner("Returned");
+    expect(banner()).toHaveTextContent(says);
+    expect(screen.getByRole("link", { name: "Open the revised report" })).toHaveAttribute(
       "href",
       `/runs/${RERUN}`,
     );
     expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
-    expect(screen.getByRole("button", { name: "Return with note" })).toBeEnabled();
+    expect(screen.getByRole("button", { name: "Return with note…" })).toBeEnabled();
   },
 );
 
@@ -289,10 +280,10 @@ it("a return whose rerun is live or completed keeps both actions off and says no
   for (const child_state of [null, "drafting" as const, "completed" as const]) {
     serveCompleted({ review: returned({ child_state }) });
     const { queryClient } = renderApp(`/runs/${RUN_ID}/review`);
-    await screen.findByRole("status", { name: "Review decision" });
-    expect(screen.queryByRole("note", { name: "Rerun outcome" })).not.toBeInTheDocument();
+    await expectBanner("Returned with a note.");
+    expect(banner()).not.toHaveTextContent("again");
     expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
-    expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
+    expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
     queryClient.clear();
     cleanup();
   }
@@ -313,7 +304,7 @@ it("returns again after a failed rerun, offering the previous note (R-M15-4)", a
     http.get(`*/api/runs/${second.run_id}`, () => HttpResponse.json(second)),
   );
   const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   const note = screen.getByRole("textbox", { name: "Note for the writer" });
   expect(note).toHaveValue("Add the 2027 date");
   await user.type(note, " and the tariff");
@@ -336,14 +327,12 @@ it("an open Review page keeps reading the run while its rerun runs, and shows it
     http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
   );
   const { queryClient } = renderApp(`/runs/${RUN_ID}/review`);
-  await screen.findByRole("status", { name: "Review decision" });
+  await expectBanner("Returned with a note. The revised report is being written.");
   expect(runRefetchInterval(queryClient, RUN_ID)).toBe(POLL_MS); // a finished run, still read
   expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
   review = returned({ child_state: "failed", child_error: "model down" });
   await act(() => queryClient.refetchQueries({ queryKey: ["runs", RUN_ID] }));
-  expect(await screen.findByRole("note", { name: "Rerun outcome" })).toHaveTextContent(
-    "The rerun failed: model down.",
-  );
+  await expectBanner("The revised report couldn't be written: model down.");
   expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
   expect(runRefetchInterval(queryClient, RUN_ID)).toBe(false); // the rerun ended: no more reads
 });
@@ -351,19 +340,19 @@ it("an open Review page keeps reading the run while its rerun runs, and shows it
 it("keeps a note the reviewer typed when Return is reopened after a cancel", async () => {
   serveCompleted({ review: returned({ child_state: "failed" }) });
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   const note = screen.getByRole("textbox", { name: "Note for the writer" });
   await user.clear(note);
   await user.type(note, "My own words");
   await user.click(screen.getByRole("button", { name: "Cancel" }));
-  await user.click(screen.getByRole("button", { name: "Return with note" }));
+  await user.click(screen.getByRole("button", { name: "Return with note…" }));
   expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("My own words");
 });
 
 it("opens Return with an empty note when the failed return stored none", async () => {
   serveCompleted({ review: returned({ child_state: "failed", note: null }) });
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("");
 });
 
@@ -385,12 +374,12 @@ it("locks the actions again once a second return is re-read with its rerun pendi
     }),
   );
   const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   await user.click(screen.getByRole("button", { name: "Return" }));
-  await waitFor(() => expect(screen.queryByRole("note", { name: "Rerun outcome" })).toBeNull());
+  await waitFor(() => expect(banner()).not.toHaveTextContent("again"));
   expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}/review`);
   expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
-  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
+  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
 });
 
 it.each([409, 503])(
@@ -419,10 +408,10 @@ it.each([409, 503])(
     const { user } = renderApp(`/runs/${RUN_ID}/review`);
     await user.click(await screen.findByRole("button", { name: "Accept" }));
     expect(await screen.findByRole("alert")).toHaveTextContent("was returned already");
-    await waitFor(() => expect(screen.queryByRole("note", { name: "Rerun outcome" })).toBeNull());
+    await waitFor(() => expect(banner()).not.toHaveTextContent("again"));
     expect(reads).toBeGreaterThan(1);
     expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
-    expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
+    expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
   },
 );
 
@@ -447,16 +436,14 @@ it("a stale page whose report another reviewer accepted shows the refusal, then
     }),
   );
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
-  await user.click(await screen.findByRole("button", { name: "Return with note" }));
+  await user.click(await screen.findByRole("button", { name: "Return with note…" }));
   await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "One more pass");
   await user.click(screen.getByRole("button", { name: "Return" }));
   expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
     "was accepted; start a new run to change it",
   );
   await user.click(screen.getByRole("button", { name: "Cancel" }));
-  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
-    "Accepted",
-  );
+  await expectBanner("Accepted");
   expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
-  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
+  expect(screen.getByRole("button", { name: "Return with note…" })).toBeDisabled();
 });
```

```diff
diff --git a/web/src/pages/review/ReviewPage.test.tsx b/web/src/pages/review/ReviewPage.test.tsx
index 8b25bf3..37addb7 100644
--- a/web/src/pages/review/ReviewPage.test.tsx
+++ b/web/src/pages/review/ReviewPage.test.tsx
@@ -5,6 +5,7 @@ import {
   claimProvenance,
   degradedReportJson,
   findings,
+  project,
   reportHtml,
   reportJson,
   resolvedPack,
@@ -12,9 +13,12 @@ import {
   runProgress,
   runTrace,
 } from "../../test/fixtures";
+import { expectNoEngineWords, visiblePrimaryButtons } from "../../test/engine-words";
 import { renderApp } from "../../test/render";
 import { server } from "../../test/server";
 
+const banner = () => screen.getByRole("status", { name: "Where the review stands" });
+
 const tabHandlers = [
   http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
   http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
@@ -42,12 +46,12 @@ it("shows the title, status and tabs for a completed run, with the claim in the
   );
   const { router, user } = renderApp(`/runs/${RUN_ID}/review?claim=c3&tab=sources`);
   expect(await screen.findByRole("heading", { name: reportJson.title })).toBeInTheDocument();
-  expect(screen.getByText("Findings open")).toBeInTheDocument();
-  expect(screen.getByText("1 finding open at delivery")).toBeInTheDocument();
+  expect(screen.getByText("1 standard not met").closest(".pill")).toBeInTheDocument();
+  expect(banner()).toHaveTextContent("Ready to review. 1 standard not met.");
   expect(screen.getByRole("tab", { name: "Sources" })).toHaveAttribute("aria-selected", "true");
-  await user.click(screen.getByRole("tab", { name: "Audit" }));
+  await user.click(screen.getByRole("tab", { name: "Standards" }));
   expect(router.state.location.search).toBe("?claim=c3&tab=audit");
-  expect(screen.queryByRole("region", { name: "Incomplete at delivery" })).toBeNull();
+  expect(banner()).not.toHaveTextContent("Delivered without a full check");
 }, 15_000);
 
 it("sends the analyst to the progress screen while the run is not complete", async () => {
@@ -55,7 +59,7 @@ it("sends the analyst to the progress screen while the run is not complete", asy
     http.get(`*/api/runs/${RUN_ID}`, () => HttpResponse.json(runProgress({ state: "drafting" }))),
   );
   renderApp(`/runs/${RUN_ID}/review`);
-  expect(await screen.findByText("This run has no report yet.")).toBeInTheDocument();
+  expect(await screen.findByText("This report has not been written yet.")).toBeInTheDocument();
   expect(screen.getByRole("link", { name: "See its progress" })).toHaveAttribute(
     "href",
     `/runs/${RUN_ID}`,
@@ -100,7 +104,7 @@ it("selects a claim from the report, opens provenance, and pluralises open findi
     ),
   );
   const { router } = renderApp(`/runs/${RUN_ID}/review?tab=audit`);
-  expect(await screen.findByText("2 findings open at delivery")).toBeInTheDocument();
+  await waitFor(() => expect(banner()).toHaveTextContent("2 standards not met."));
   const frame = (await screen.findByTitle("Report")) as HTMLIFrameElement;
   expect(frame.getAttribute("srcdoc")).toContain('p data-claim-ids="c1"');
   act(() => {
@@ -126,7 +130,7 @@ it("selecting a claim in the Provenance tab puts it in the URL", async () => {
   const list = await screen.findByRole("list", { name: "Claims" });
   await user.click(within(list).getAllByRole("button")[1]!);
   await waitFor(() => expect(router.state.location.search).toBe("?claim=c3"));
-  expect(await screen.findByRole("list", { name: "Evidence for c3" })).toBeInTheDocument();
+  expect(await screen.findByRole("list", { name: "Evidence for claim c3" })).toBeInTheDocument();
 }, 15_000);
 
 it("shows a failed report.json on the header and falls back to a plain title", async () => {
@@ -158,15 +162,79 @@ it("lists what did not complete when the report was delivered degraded", async (
     ...tabHandlers,
   );
   const { user } = renderApp(`/runs/${RUN_ID}/review`);
-  const notice = await screen.findByRole("region", { name: "Incomplete at delivery" });
-  expect(notice).toHaveTextContent("delivered without every stage completing");
-  expect(within(notice).getByRole("listitem")).toHaveTextContent(AUDIT_INCOMPLETE);
-  expect(screen.getByText("Findings open")).toBeInTheDocument();
-  await user.click(screen.getByRole("tab", { name: "Audit" }));
+  await waitFor(() =>
+    expect(banner()).toHaveTextContent(
+      "Delivered without a full check. The standards check didn't finish after 2 attempts.",
+    ),
+  );
+  // the engine's error stays under Details (M18 spec §4.1)
+  const details = within(banner()).getByText("Details").closest("details")!;
+  expect(details).not.toHaveAttribute("open");
+  expect(within(details).getByRole("listitem")).toHaveTextContent(
+    AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2),
+  );
+  expect(screen.getByText("Checked in part")).toBeInTheDocument();
+  await user.click(screen.getByRole("tab", { name: "Standards" }));
   expect(
     await screen.findByText(
-      "The audit did not complete: auditor: invalid output after repair: " +
+      "The standards check didn't finish: auditor: invalid output after repair: " +
         "findings.icd203.as.1: Field required",
     ),
   ).toBeInTheDocument();
 }, 15_000);
+
+function serveReview(json = reportJson) {
+  server.use(
+    http.get("*/api/projects", () => HttpResponse.json([project])),
+    http.get(`*/api/runs/${RUN_ID}`, () =>
+      HttpResponse.json(runProgress({ state: "completed", status: json.metadata.status })),
+    ),
+    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
+    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(json)),
+    ...tabHandlers,
+  );
+}
+
+it("leads back to the project, names the tab, and has Accept as its one primary button", async () => {
+  serveReview();
+  renderApp(`/runs/${RUN_ID}/review`);
+  const main = screen.getByRole("main");
+  await within(main).findByRole("heading", { name: reportJson.title });
+  const crumb = within(main).getByRole("navigation", { name: "Breadcrumb" });
+  expect(within(crumb).getByRole("link", { name: project.name })).toHaveAttribute(
+    "href",
+    `/new?project=${project.id}`,
+  );
+  expect(within(main).getByText("Meets the standards").closest(".pill")).toBeInTheDocument();
+  expect(visiblePrimaryButtons(main)).toHaveLength(1);
+  expect(within(main).getByRole("button", { name: "Accept" })).toHaveClass("primary");
+  expect(
+    within(main)
+      .getAllByRole("tab")
+      .map((tab) => tab.textContent),
+  ).toEqual(["Claims", "Standards", "Process", "Sources"]);
+  await waitFor(() => expect(document.title).toBe(`${reportJson.title} – Corelata`));
+});
+
+it("opens the standards not met from the banner", async () => {
+  serveReview({
+    ...reportJson,
+    metadata: { ...reportJson.metadata, status: "findings_open", open_findings: ["icd203.tc.8@1"] },
+  });
+  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
+  await screen.findByRole("status", { name: "Where the review stands" });
+  await user.click(await within(banner()).findByRole("button", { name: "Show them" }));
+  expect(router.state.location.search).toBe("?tab=audit");
+  expect(screen.getByRole("tab", { name: "Standards" })).toHaveAttribute("aria-selected", "true");
+});
+
+it("shows no engine word in the header, the banner, the claims and the standards (M18 spec §4)", async () => {
+  serveReview();
+  const { user } = renderApp(`/runs/${RUN_ID}/review?claim=c3`);
+  const main = screen.getByRole("main");
+  await within(main).findByRole("list", { name: "Evidence for claim c3" });
+  expectNoEngineWords(main);
+  await user.click(screen.getByRole("tab", { name: "Standards" }));
+  await within(main).findByRole("list", { name: "Met and not applicable" });
+  expectNoEngineWords(main);
+}, 15_000);
```

```diff
diff --git a/web/src/pages/review/AuditTab.test.tsx b/web/src/pages/review/AuditTab.test.tsx
index 478beec..7dcf150 100644
--- a/web/src/pages/review/AuditTab.test.tsx
+++ b/web/src/pages/review/AuditTab.test.tsx
@@ -27,26 +27,30 @@ it("builds one row per rule with the latest verdict and the iteration history",
   ]);
 });
 
-it("groups verifiable and advisory rules and shows severity, evidence and history", async () => {
+it("groups the rules met and advisory, each with its verdict, severity, why and history", async () => {
   server.use(
     http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
     http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
     http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
   );
   renderWithClient(<AuditTab runId={RUN_ID} />);
-  const verifiable = await screen.findByRole("table", { name: "Verifiable rules" });
-  const row = within(verifiable).getAllByRole("row")[1]!;
-  expect(row).toHaveTextContent("Sourcing is clear");
-  expect(row).toHaveTextContent("blocking");
-  expect(row).toHaveTextContent("Every claim cites a unit.");
-  expect(within(row).getByLabelText("Verdict history")).toHaveTextContent("fail → pass");
-  const advisory = screen.getByRole("table", { name: "Advisory rules" });
-  expect(within(advisory).getAllByRole("row")[1]).toHaveTextContent(
+  const met = await screen.findByRole("list", { name: "Met and not applicable" });
+  const rule = within(met).getByRole("listitem");
+  expect(rule).toHaveTextContent("Sourcing is clear");
+  expect(rule).toHaveTextContent("icd203.tc.8");
+  expect(rule).toHaveTextContent("✓ met");
+  expect(rule).toHaveTextContent("Blocking");
+  const why = within(rule).getByText("Why").closest("details")!;
+  expect(why).not.toHaveAttribute("open");
+  expect(why).toHaveTextContent("Every claim cites a unit.");
+  expect(within(rule).getByLabelText("History")).toHaveTextContent("✗ not met → ✓ met");
+  expect(screen.queryByRole("list", { name: "Not met" })).toBeNull();
+  const advisory = screen.getByRole("list", { name: "Advisory" });
+  expect(within(advisory).getByRole("listitem")).toHaveTextContent(
     "Consistent with prior analysis",
   );
-  expect(
-    screen.getByText("Every verifiable rule passed in the last iteration."),
-  ).toBeInTheDocument();
+  expect(within(advisory).getByRole("listitem")).toHaveTextContent("◇ attested");
+  expect(screen.getByText("Every standard that could be checked was met.")).toBeInTheDocument();
 });
 
 it("falls back to rule ids when the pack cannot be resolved", async () => {
@@ -58,8 +62,10 @@ it("falls back to rule ids when the pack cannot be resolved", async () => {
     ),
   );
   renderWithClient(<AuditTab runId={RUN_ID} />);
-  const table = await screen.findByRole("table", { name: "Rules" });
-  expect(within(table).getAllByRole("row")).toHaveLength(3);
+  // without the pack nothing says which rules are advisory: they group by verdict alone
+  const met = await screen.findByRole("list", { name: "Met and not applicable" });
+  expect(within(met).getAllByRole("listitem")).toHaveLength(2);
+  expect(within(met).getAllByRole("listitem")[0]).toHaveTextContent("icd203.tc.8");
   expect(
     await screen.findByText("Rule titles are unavailable: pack 'icd203-base' not found"),
   ).toBeInTheDocument();
@@ -84,7 +90,7 @@ it("says so when no findings were recorded", async () => {
     http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
   );
   renderWithClient(<AuditTab runId={RUN_ID} />);
-  expect(await screen.findByText("No audit findings were recorded.")).toBeInTheDocument();
+  expect(await screen.findByText("No standards results were recorded.")).toBeInTheDocument();
 });
 
 it("shows the recommendation and no pass notice while a verifiable rule is failing", async () => {
@@ -100,10 +106,13 @@ it("shows the recommendation and no pass notice while a verifiable rule is faili
   );
   renderWithClient(<AuditTab runId={RUN_ID} />);
   expect((await screen.findAllByText("Cite a unit.")).length).toBeGreaterThan(0);
-  expect(screen.queryByText("Every verifiable rule passed in the last iteration.")).toBeNull();
+  // not met comes first, and the advisory rule stays advisory whatever its verdict
+  const groups = screen.getAllByRole("list").map((l) => l.getAttribute("aria-label"));
+  expect(groups).toEqual(["Not met", "Advisory"]);
+  expect(screen.queryByText("Every standard that could be checked was met.")).toBeNull();
 });
 
-it("shows a loading state for the rule titles instead of reflowing the table", async () => {
+it("shows a loading state for the rule titles instead of reflowing the rules", async () => {
   const pack = deferred();
   server.use(
     http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
@@ -115,17 +124,15 @@ it("shows a loading state for the rule titles instead of reflowing the table", a
   );
   renderWithClient(<AuditTab runId={RUN_ID} />);
   expect(await screen.findByText(/Loading rule titles/)).toBeInTheDocument();
-  expect(screen.queryByRole("table", { name: "Rules" })).not.toBeInTheDocument();
+  expect(screen.queryByRole("list", { name: "Met and not applicable" })).not.toBeInTheDocument();
   pack.resolve();
-  expect(await screen.findByRole("table", { name: "Verifiable rules" })).toBeInTheDocument();
-  expect(
-    within(screen.getByRole("table", { name: "Verifiable rules" })).getByText("Sourcing is clear"),
-  ).toHaveAttribute("dir", "auto");
+  const met = await screen.findByRole("list", { name: "Met and not applicable" });
+  expect(within(met).getByText("Sourcing is clear")).toHaveAttribute("dir", "auto");
 });
 
 const REASON = AUDIT_INCOMPLETE.slice(AUDIT_INCOMPLETE.indexOf(": ") + 2);
 
-it("says the audit did not complete instead of saying no findings were recorded", async () => {
+it("says the standards check did not finish instead of saying nothing was recorded", async () => {
   server.use(
     http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
     http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
@@ -137,8 +144,10 @@ it("says the audit did not complete instead of saying no findings were recorded"
       degradations={["conveyance skipped after 2 attempts: x", AUDIT_INCOMPLETE]}
     />,
   );
-  expect(await screen.findByText(`The audit did not complete: ${REASON}`)).toBeInTheDocument();
-  expect(screen.queryByText("No audit findings were recorded.")).toBeNull();
+  expect(
+    await screen.findByText(`The standards check didn't finish: ${REASON}`),
+  ).toBeInTheDocument();
+  expect(screen.queryByText("No standards results were recorded.")).toBeNull();
 });
 
 it("shows the whole entry when it has no colon", async () => {
@@ -148,20 +157,20 @@ it("shows the whole entry when it has no colon", async () => {
     http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
   );
   renderWithClient(<AuditTab runId={RUN_ID} degradations={["audit incomplete"]} />);
-  const note = await screen.findByText("The audit did not complete: audit incomplete");
+  const note = await screen.findByText("The standards check didn't finish: audit incomplete");
   expect(note).toHaveAttribute("dir", "auto");
 });
 
-it("keeps the previous audit's rows without the pass notice", async () => {
+it("keeps the previous check's rules without the met notice", async () => {
   server.use(
     http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
     http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
     http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
   );
   renderWithClient(<AuditTab runId={RUN_ID} degradations={[AUDIT_INCOMPLETE]} />);
-  expect(await screen.findByRole("table", { name: "Verifiable rules" })).toBeInTheDocument();
-  expect(screen.getByText(`The audit did not complete: ${REASON}`)).toBeInTheDocument();
-  expect(screen.queryByText("Every verifiable rule passed in the last iteration.")).toBeNull();
+  expect(await screen.findByRole("list", { name: "Met and not applicable" })).toBeInTheDocument();
+  expect(screen.getByText(`The standards check didn't finish: ${REASON}`)).toBeInTheDocument();
+  expect(screen.queryByText("Every standard that could be checked was met.")).toBeNull();
 });
 
 it("ignores a conveyance degradation", async () => {
@@ -173,5 +182,5 @@ it("ignores a conveyance degradation", async () => {
   renderWithClient(
     <AuditTab runId={RUN_ID} degradations={["conveyance skipped after 2 attempts: x"]} />,
   );
-  expect(await screen.findByText("No audit findings were recorded.")).toBeInTheDocument();
+  expect(await screen.findByText("No standards results were recorded.")).toBeInTheDocument();
 });
```

```diff
diff --git a/web/src/pages/review/ProvenanceTab.test.tsx b/web/src/pages/review/ProvenanceTab.test.tsx
index abcd0db..1e640b8 100644
--- a/web/src/pages/review/ProvenanceTab.test.tsx
+++ b/web/src/pages/review/ProvenanceTab.test.tsx
@@ -33,24 +33,23 @@ it("lists the claims, selects one and shows its evidence with locators and sourc
   const list = await screen.findByRole("list", { name: "Claims" });
   const items = within(list).getAllByRole("listitem");
   expect(items).toHaveLength(2);
-  expect(items[1]).toHaveTextContent("judgment");
-  expect(items[1]).toHaveTextContent("likely");
+  expect(items[1]).toHaveTextContent("Judgment · likely · 2 passages");
   await user.click(within(items[1]!).getByRole("button"));
-  const evidence = await screen.findByRole("list", { name: "Evidence for c3" });
+  const evidence = await screen.findByRole("list", { name: "Evidence for claim c3" });
   const units = within(evidence).getAllByRole("listitem");
   expect(units).toHaveLength(2);
   expect(units[0]).toHaveTextContent("port.txt");
   expect(units[0]).toHaveTextContent("para:2");
   expect(units[0]).toHaveTextContent("Shippers expect waiting times");
   expect(
-    screen.getByText("Cited in: key_judgments[0], analysis[0].paragraphs[1]"),
+    screen.getByText("Cited in: Key judgments, item 1; Analysis, section 1, paragraph 2"),
   ).toBeInTheDocument();
   expect(within(items[1]!).getByRole("button")).toHaveAttribute("aria-pressed", "true");
 });
 
 it("shows the evidence for a claim selected from the report (URL) and a claim lookup error", async () => {
   renderWithClient(<Host initial="c1" />);
-  expect(await screen.findByRole("list", { name: "Evidence for c1" })).toBeInTheDocument();
+  expect(await screen.findByRole("list", { name: "Evidence for claim c1" })).toBeInTheDocument();
   server.use(
     http.get(`*/api/runs/${RUN_ID}/claims/c9`, () =>
       HttpResponse.json({ detail: "claim c9 is not in the report" }, { status: 404 }),
@@ -74,7 +73,7 @@ it("says the evidence is loading while a selected claim's evidence loads (CRL-40
   await user.click(within(within(list).getAllByRole("listitem")[1]!).getByRole("button"));
   expect(await screen.findByText("Loading evidence…")).toHaveAttribute("role", "status");
   held.resolve();
-  expect(await screen.findByRole("list", { name: "Evidence for c3" })).toBeInTheDocument();
+  expect(await screen.findByRole("list", { name: "Evidence for claim c3" })).toBeInTheDocument();
   expect(screen.queryByText("Loading evidence…")).not.toBeInTheDocument();
 });
```

```diff
diff --git a/web/src/pages/review/ProcessTab.test.tsx b/web/src/pages/review/ProcessTab.test.tsx
index 2e941ba..b21c992 100644
--- a/web/src/pages/review/ProcessTab.test.tsx
+++ b/web/src/pages/review/ProcessTab.test.tsx
@@ -10,7 +10,10 @@ it("shows the stage timeline, what each draft changed and the usage by role", as
   renderWithClient(<ProcessTab runId={RUN_ID} />);
   const stages = await screen.findByRole("table", { name: "Stage timeline" });
   expect(within(stages).getAllByRole("row")).toHaveLength(10);
-  expect(within(stages).getAllByRole("row")[2]).toHaveTextContent("Checking the value");
+  // the reader's word, then the engine's (M18 spec §4.4)
+  expect(within(stages).getAllByRole("row")[2]).toHaveTextContent(
+    "Checking the value statement (gating)",
+  );
   expect(within(stages).getAllByRole("row")[2]).toHaveTextContent("2.3 s");
   const drafts = screen.getByRole("list", { name: "Drafts" });
   const items = within(drafts).getAllByRole("listitem");
```

```diff
diff --git a/web/src/pages/review/SourcesTab.test.tsx b/web/src/pages/review/SourcesTab.test.tsx
index 000ba56..dd10389 100644
--- a/web/src/pages/review/SourcesTab.test.tsx
+++ b/web/src/pages/review/SourcesTab.test.tsx
@@ -18,8 +18,8 @@ it("lists the run's sources with kind, units, digest flag and Coglossa run id",
   expect(rows[1]).toHaveTextContent("cccccccccccc");
   expect(within(table).getByRole("columnheader", { name: "SHA-256" })).toBeInTheDocument();
   expect(rows[1]).toHaveTextContent("Coglossa run run-42");
-  expect(rows[1]).toHaveTextContent("digested");
-  expect(screen.getByText(/Pack icd203-base/)).toBeInTheDocument();
+  expect(rows[1]).toHaveTextContent("summarised before drafting");
+  expect(screen.getByText(/Standards pack icd203-base \(bbbbbbbbbbbb\)/)).toBeInTheDocument();
 });
 
 it("shows a trace error", async () => {
@@ -50,5 +50,5 @@ it("shows the profile, a missing Coglossa run id and singular units", async () =
   expect(row).toHaveTextContent("Coglossa run ?");
   expect(row).toHaveTextContent("1 unit");
   expect(row).not.toHaveTextContent("1 units");
-  expect(screen.getByText(/profile brief/)).toBeInTheDocument();
+  expect(screen.getByText(/team profile brief/)).toBeInTheDocument();
 });
```

```diff
diff --git a/web/src/lib/status.test.ts b/web/src/lib/status.test.ts
index b30c13d..ceda4b3 100644
--- a/web/src/lib/status.test.ts
+++ b/web/src/lib/status.test.ts
@@ -1,6 +1,13 @@
 import type { RunState } from "../api/types";
 import { project, runProgress, runSummary } from "../test/fixtures";
-import { fromProgress, fromSummary, projectStatus, runStatus, type RunLike } from "./status";
+import {
+  fromProgress,
+  fromSummary,
+  projectStatus,
+  reportStatus,
+  runStatus,
+  type RunLike,
+} from "./status";
 
 const run = (
   state: RunState,
@@ -72,3 +79,9 @@ it("gives a project the first status that holds (spec §3.3)", () => {
   // anything else: the latest report's own status (R-M18-6)
   expect(p({ latest_run: latest("completed", "returned") })).toBe("↺ returned (none)");
 });
+
+it("gives a delivered report's status pill its words and symbol (spec §4.1)", () => {
+  expect(shown(reportStatus("clean", 0))).toBe("✓ Meets the standards (ok)");
+  expect(shown(reportStatus("findings_open", 2))).toBe("✗ 2 standards not met (warn)");
+  expect(shown(reportStatus("findings_open", 0))).toBe("⚠ Checked in part (warn)");
+});
```

```diff
diff --git a/web/src/lib/words.test.ts b/web/src/lib/words.test.ts
index cf5d3e7..c64e8ac 100644
--- a/web/src/lib/words.test.ts
+++ b/web/src/lib/words.test.ts
@@ -7,6 +7,7 @@ import {
   PROGRESS_STEPS,
   reportStatusText,
   SEVERITY,
+  severityText,
   STEP_LABEL,
   VERDICT,
 } from "./words";
@@ -69,3 +70,8 @@ it("words a report's status", () => {
   expect(reportStatusText("findings_open", 0)).toBe("Checked in part");
   expect(plural(2, "passage")).toBe("2 passages");
 });
+
+it("capitalises a finding's severity, a pack's own word too", () => {
+  expect(severityText("blocking")).toBe("Blocking");
+  expect(severityText("critical")).toBe("Critical");
+});
```

```diff
diff --git a/web/src/lib/format.test.ts b/web/src/lib/format.test.ts
index 96618e3..46b7a36 100644
--- a/web/src/lib/format.test.ts
+++ b/web/src/lib/format.test.ts
@@ -6,11 +6,9 @@ import {
   isTerminal,
   splitIds,
   STAGES,
-  STATE_LABELS,
 } from "./format";
 
-it("labels every state and knows the terminal ones", () => {
-  expect(Object.keys(STATE_LABELS)).toHaveLength(11);
+it("knows the terminal states and the stages in order", () => {
   expect(isTerminal("completed")).toBe(true);
   expect(isTerminal("drafting")).toBe(false);
   expect(STAGES).toEqual(["ingesting", "gating", "drafting", "conveying", "auditing", "rendering"]);
```

A closed dialog's primary button is not on screen; and a Coglossa locator is not an engine word:

```diff
diff --git a/web/src/test/engine-words.ts b/web/src/test/engine-words.ts
index 395e4d1..adfc9cc 100644
--- a/web/src/test/engine-words.ts
+++ b/web/src/test/engine-words.ts
@@ -1,7 +1,8 @@
 /** The engine's words that must not reach the main flow (M18 spec §4, success criterion 4).
- * "run" stays allowed in "Coglossa run <id>" (a Coglossa run is Coglossa's word, §5.2). */
+ * "run" stays allowed in "Coglossa run <id>" and in a Coglossa locator ("coglossa:<run id>/…"):
+ * a Coglossa run is Coglossa's word (§5.2), and locators are shown as they are (§4.1). */
 export const ENGINE_WORDS =
-  /(?<!Coglossa |Coglossa run )\b(runs?|reruns?|discovery|discoveries|gate|gating|audit(s|ing)?|conveyor|conveying|conveyed|ingesting|iterations?|verdicts?|evidence units?|findings?|digested|pack)\b/i;
+  /(?<!Coglossa |Coglossa run |coglossa:)\b(runs?|reruns?|discovery|discoveries|gate|gating|audit(s|ing)?|conveyor|conveying|conveyed|ingesting|iterations?|verdicts?|evidence units?|findings?|digested|pack)\b/i;
 
 /** The page's visible words: its text, its buttons' and fields' names, and its live regions'
  * labels, so a reworded heading cannot hide an engine word in an aria-label. */
@@ -12,6 +13,13 @@ export function screenWords(root: HTMLElement): string {
   return [root.textContent ?? "", ...labels].join(" \n ");
 }
 
+/** The primary buttons a person can see: a closed dialog's are not on screen. */
+export function visiblePrimaryButtons(root: HTMLElement): HTMLElement[] {
+  return [...root.querySelectorAll<HTMLElement>("button.primary, a.button.primary")].filter(
+    (el) => !el.closest("dialog:not([open])"),
+  );
+}
+
 export function expectNoEngineWords(root: HTMLElement): void {
   expect(screenWords(root)).not.toMatch(ENGINE_WORDS);
 }
```

```diff
diff --git a/web/src/pages/new/NewRunPage.test.tsx b/web/src/pages/new/NewRunPage.test.tsx
index 2f4bbda..6fb1b23 100644
--- a/web/src/pages/new/NewRunPage.test.tsx
+++ b/web/src/pages/new/NewRunPage.test.tsx
@@ -14,7 +14,7 @@ import {
   runSummary,
   sources,
 } from "../../test/fixtures";
-import { expectNoEngineWords } from "../../test/engine-words";
+import { expectNoEngineWords, visiblePrimaryButtons } from "../../test/engine-words";
 import { renderApp } from "../../test/render";
 import { server } from "../../test/server";
 
@@ -262,7 +262,7 @@ it("the project page names the project, has no picker, folds the options and has
   expect(options).not.toHaveAttribute("open");
   expect(within(options).getByRole("combobox", { name: "Team profile" })).toBeInTheDocument();
   expect(within(options).getByRole("spinbutton", { name: "Revision rounds" })).toHaveValue(2);
-  expect(main.querySelectorAll("button.primary")).toHaveLength(1);
+  expect(visiblePrimaryButtons(main)).toHaveLength(1);
   expect(within(main).getByRole("button", { name: "Write the report" })).toHaveClass("primary");
 });
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/pages/review src/lib src/pages/new/NewRunPage.test.tsx`
Expected: FAIL: `Failed to resolve import "./ReviewBanner"`; `frameTheme.test.tsx`: `HIGHLIGHT_CSS` lacks the theme classes and the root has no class; the review tests find no "Where the review stands" status, no "Download" menu, no "Claims" or "Standards" tab; `reportStatus` and `severityText` are not exported.

- [ ] **Step 3: The bridge and the frame (R-M18-2, R-M18-10)**

```diff
diff --git a/web/src/pages/review/frameBridge.ts b/web/src/pages/review/frameBridge.ts
index ad4d167..2c2a1e3 100644
--- a/web/src/pages/review/frameBridge.ts
+++ b/web/src/pages/review/frameBridge.ts
@@ -6,10 +6,17 @@ import { REPORT_STYLE_HASH } from "virtual:report-style";
  * ready; the page posts the claim to highlight. */
 
 export type FrameToHost = { type: "corelata:ready" } | { type: "corelata:select"; claim: string };
-export type HostToFrame = { type: "corelata:highlight"; claim: string | null; scroll: boolean };
+export type HostToFrame =
+  | { type: "corelata:highlight"; claim: string | null; scroll: boolean }
+  | { type: "corelata:theme"; theme: "light" | "dark" };
 
+/** The bridge's own stylesheet, bound to the frame's nonce: the claim highlight, and the two
+ * classes that set the report's colour scheme to the app's theme (M18 spec §5.5, R-M18-2). The
+ * report's stylesheet says `color-scheme: light dark` on `:root`; a class on the frame's root is
+ * more specific, so the app's choice wins over the computer's. */
 export const HIGHLIGHT_CSS =
-  ".corelata-highlight { background: #fff3b0; color: #1a1a1a; outline: 2px solid #e0a800; outline-offset: 2px; }";
+  ".corelata-highlight { background: #fff3b0; color: #1a1a1a; outline: 2px solid #e0a800; outline-offset: 2px; }" +
+  " :root.corelata-theme-light { color-scheme: light; } :root.corelata-theme-dark { color-scheme: dark; }";
 
 /** Installed inside the frame. Self-contained on purpose: `bridgeScript()` serialises it with
  * `Function.prototype.toString`, so its body may not reference anything outside itself. */
@@ -19,7 +26,14 @@ export function installFrameBridge(
   listen: (handler: (message: HostToFrame) => void) => void,
   css: string,
   nonce: string,
+  theme = "",
 ): void {
+  const setTheme = (next: string) => {
+    if (next !== "light" && next !== "dark") return;
+    doc.documentElement.classList.remove("corelata-theme-light", "corelata-theme-dark");
+    doc.documentElement.classList.add(`corelata-theme-${next}`);
+  };
+  setTheme(theme); // the theme the page had when it built the frame: no flash of the other one
   const style = doc.createElement("style");
   if (nonce) style.setAttribute("nonce", nonce); // the frame's policy allows this style by nonce
   style.textContent = css;
@@ -32,6 +46,7 @@ export function installFrameBridge(
     if (first) post({ type: "corelata:select", claim: first });
   });
   listen((message) => {
+    if (message && message.type === "corelata:theme") return setTheme(message.theme);
     if (!message || message.type !== "corelata:highlight") return;
     for (const el of doc.querySelectorAll(".corelata-highlight"))
       el.classList.remove("corelata-highlight");
@@ -60,26 +75,32 @@ export function cspMeta(nonce: string): string {
   return `<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP(nonce)}">`;
 }
 
-/** The `<script>` that installs the bridge: it talks to `parent` and trusts only `parent`. */
-export function bridgeScript(nonce?: string): string {
+/** The `<script>` that installs the bridge: it talks to `parent` and trusts only `parent`.
+ * `theme` is the app's theme when the page builds the frame (R-M18-10). */
+export function bridgeScript(nonce?: string, theme?: "light" | "dark"): string {
   const attr = nonce ? ` nonce="${nonce}"` : "";
+  const initial = theme ? `, ${JSON.stringify(theme)}` : "";
   return (
     `<script${attr}>(${installFrameBridge.toString()})(document,` +
     ' function (m) { parent.postMessage(m, "*"); },' +
     ' function (h) { addEventListener("message", function (e) { if (e.source === parent) h(e.data); }); },' +
-    ` ${JSON.stringify(HIGHLIGHT_CSS)}, ${JSON.stringify(nonce ?? "")});</script>`
+    ` ${JSON.stringify(HIGHLIGHT_CSS)}, ${JSON.stringify(nonce ?? "")}${initial});</script>`
   );
 }
 
 /** The report with its policy at the top of `<head>`, whatever the tag's attributes (R-M10-8);
  * right after the doctype when there is no head (so the document stays in standards mode); else
  * at the very start. The bridge is appended inside `<body>` (or at the end). */
-export function withBridge(html: string, nonce: string = frameNonce()): string {
+export function withBridge(
+  html: string,
+  nonce: string = frameNonce(),
+  theme?: "light" | "dark",
+): string {
   const meta = cspMeta(nonce);
   const anchor = /<head\b[^>]*>/i.exec(html) ?? /^\s*<!doctype\b[^>]*>/i.exec(html);
   const cut = anchor ? anchor.index + anchor[0].length : 0;
   const withMeta = html.slice(0, cut) + meta + html.slice(cut);
-  const script = bridgeScript(nonce);
+  const script = bridgeScript(nonce, theme);
   const at = [...withMeta.matchAll(/<\/body\s*>/gi)].at(-1)?.index; // length-preserving search
   return at === undefined ? withMeta + script : withMeta.slice(0, at) + script + withMeta.slice(at);
 }
```

Replace `web/src/pages/review/ReportFrame.tsx`:

```tsx
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "../../theme/theme";
import { type FrameToHost, type HostToFrame, withBridge } from "./frameBridge";

/** The rendered report (spec §9, claim ids on) in a sandboxed frame with no origin of its own:
 * its stylesheet stays inside, nothing in it can touch the page, and the bridge script in the
 * document is the only channel (M7). The document carries its own Content-Security-Policy (M9).
 * The page tells the frame which claim to highlight and which theme to show (M18 spec §5.5); the
 * frame tells the page which cited element a reader clicked. */
export function ReportFrame({
  html,
  selectedClaim,
  onSelectClaim,
}: {
  html: string;
  selectedClaim: string | null;
  onSelectClaim: (claimId: string) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const select = useRef(onSelectClaim);
  const fromFrame = useRef(false); // the last selection came from a click inside the frame
  const current = useRef(selectedClaim);
  const { theme } = useTheme();
  // The frame is built with the theme the page had first, so it opens in it; a later change is
  // a message, not a new document (R-M18-10). `shown` is the theme the frame shows now.
  const [builtWith] = useState(theme);
  const shown = useRef(builtWith);
  // The message handler reads the latest callback and selection; they are copied after each
  // render commits (refs are not written during render) and before any later message arrives.
  useLayoutEffect(() => {
    select.current = onSelectClaim;
    current.current = selectedClaim;
  });
  const [ready, setReady] = useState(0); // bumps each time a loaded frame's bridge reports in
  const srcdoc = useMemo(() => withBridge(html, undefined, builtWith), [html, builtWith]);

  useEffect(() => {
    const onMessage = (event: MessageEvent<FrameToHost | null>) => {
      if (!event.source || event.source !== frame.current?.contentWindow) return;
      const message = event.data;
      if (typeof message !== "object" || message === null) return;
      if (message.type === "corelata:ready") {
        shown.current = builtWith; // a (re)loaded frame starts in the theme it was built with
        setReady((n) => n + 1);
      } else if (
        message.type === "corelata:select" &&
        typeof message.claim === "string" &&
        message.claim.length > 0 &&
        message.claim.length <= 200 // a hostile in-frame script cannot push junk into the URL
      ) {
        fromFrame.current = message.claim !== current.current;
        select.current(message.claim);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [builtWith]);

  // The highlight follows the selection, once there is a frame to tell.
  useEffect(() => {
    if (!ready) return;
    const message: HostToFrame = {
      type: "corelata:highlight",
      claim: selectedClaim,
      scroll: !fromFrame.current,
    };
    frame.current?.contentWindow?.postMessage(message, "*"); // the frame has no origin to name
    fromFrame.current = false;
  }, [selectedClaim, ready]);

  // The frame follows the app's theme: on a change, and on a frame that reloaded after one.
  useEffect(() => {
    if (!ready || theme === shown.current) return;
    const message: HostToFrame = { type: "corelata:theme", theme };
    frame.current?.contentWindow?.postMessage(message, "*");
    shown.current = theme;
  }, [theme, ready]);

  return (
    <iframe
      ref={frame}
      title="Report"
      className="report-frame"
      sandbox="allow-scripts"
      srcDoc={srcdoc}
    />
  );
}
```

- [ ] **Step 4: The words and statuses Review needs**

```diff
diff --git a/web/src/lib/words.ts b/web/src/lib/words.ts
index 6ef5ae2..c8e5d3c 100644
--- a/web/src/lib/words.ts
+++ b/web/src/lib/words.ts
@@ -54,6 +54,12 @@ export const SEVERITY: Record<Severity, string> = {
   minor: "Minor",
 };
 
+/** A finding carries its rule's severity as text: the pack's words, capitalised. */
+export function severityText(severity: string): string {
+  const known = (SEVERITY as Record<string, string | undefined>)[severity];
+  return known ?? severity.charAt(0).toUpperCase() + severity.slice(1);
+}
+
 export const CLAIM_KIND: Record<ClaimKind, string> = {
   fact: "Fact",
   judgment: "Judgment",
```

```diff
diff --git a/web/src/lib/status.ts b/web/src/lib/status.ts
index 07ffecc..b4008a7 100644
--- a/web/src/lib/status.ts
+++ b/web/src/lib/status.ts
@@ -1,4 +1,12 @@
-import type { ProjectView, ReviewDecision, RunProgress, RunState, RunSummary } from "../api/types";
+import type {
+  ProjectView,
+  ReportStatus,
+  ReviewDecision,
+  RunProgress,
+  RunState,
+  RunSummary,
+} from "../api/types";
+import { reportStatusText } from "./words";
 
 /** Copied from Coglossa's lib/status.ts (spec §2.2): the tone classes are base.css's `tone-*`. */
 export type Tone = "ok" | "warn" | "busy" | "bad" | "none";
@@ -57,6 +65,13 @@ export function runStatus(run: RunLike): Status {
   }
 }
 
+/** M18 spec §4.1: a delivered report's status pill on Review. */
+export function reportStatus(status: ReportStatus, open: number): Status {
+  const text = reportStatusText(status, open);
+  if (status === "clean") return { text, symbol: "✓", tone: "ok" };
+  return { text, symbol: open > 0 ? "✗" : "⚠", tone: "warn" };
+}
+
 /** M18 spec §3.3: a project's one status in the sidebar, the first condition that holds. */
 export function projectStatus(project: ProjectView): Status {
   if (project.reports_writing > 0) return WRITING;
```

`STATE_LABELS` goes (R-M18-21):

```diff
diff --git a/web/src/lib/format.ts b/web/src/lib/format.ts
index 3a17bb5..2523ed9 100644
--- a/web/src/lib/format.ts
+++ b/web/src/lib/format.ts
@@ -1,19 +1,5 @@
 import type { RunState } from "../api/types";
 
-export const STATE_LABELS: Record<RunState, string> = {
-  created: "Queued",
-  ingesting: "Ingesting sources",
-  gating: "Checking the value",
-  drafting: "Drafting",
-  conveying: "Editing for the reader",
-  auditing: "Auditing",
-  rendering: "Rendering",
-  completed: "Completed",
-  gate_rejected: "Value not supported",
-  failed: "Failed",
-  cancelled: "Cancelled",
-};
-
 /** The pipeline's stages in order (spec §7.2); drafting, conveying and auditing repeat per
  * iteration. */
 export const STAGES = [
```

- [ ] **Step 5: The header, the banner and the tabs**

Replace `web/src/pages/review/ReviewActions.tsx`:

```tsx
import { useId, useState } from "react";
import { useNavigate } from "react-router";
import { exportUrl, reportUrl } from "../../api/client";
import { rerunFreed, useReview } from "../../api/runs";
import type { ReviewState } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Menu } from "../../components/Menu";

/** The Download menu's items (M18 spec §5.4): today's four URLs, with plain names. */
export function downloads(runId: string): [string, string][] {
  return [
    ["Word document (DOCX)", reportUrl(runId, "docx", { download: true })],
    ["Markdown", reportUrl(runId, "md", { download: true })],
    ["Web page (HTML)", reportUrl(runId, "html", { download: true })],
    ["Trace (JSON)", exportUrl(runId, "trace.json")],
  ];
}

/** The review header's actions (M18 spec §5.4): Accept, Return with note…, Download ▾. The
 * button rules are M9–M16's: both off while a request is out or once decided, on again when the
 * revision a return made ended without a report (R-M15-4), the note offered again then. */
export function ReviewActions({ runId, review }: { runId: string; review: ReviewState | null }) {
  const send = useReview(runId);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const noteId = useId();
  const busy = send.isPending;
  const freed = rerunFreed(review); // R-M15-4: Return and Accept are offered again
  const decided = review !== null && !freed;

  function accept() {
    send.mutate({ action: "accept", note: "" });
  }

  function sendReturn() {
    send.mutate(
      { action: "return", note: note.trim() },
      {
        onSuccess: (result) => {
          setOpen(false);
          setNote("");
          if (result.child) navigate(`/runs/${result.child.run_id}`);
        },
      },
    );
  }

  return (
    <div className="row review-actions">
      <button type="button" className="primary" onClick={accept} disabled={busy || decided}>
        Accept
      </button>
      <button
        type="button"
        onClick={() => {
          send.reset();
          if (freed && !note) setNote(review?.note ?? "");
          setOpen(true);
        }}
        disabled={busy || decided}
      >
        Return with note…
      </button>
      <Menu label="Download" button="Download ▾">
        {(close) =>
          downloads(runId).map(([name, href]) => (
            <a key={href} role="menuitem" href={href} onClick={close}>
              {name}
            </a>
          ))
        }
      </Menu>
      {send.error && !open ? <ErrorMessage error={send.error} /> : null}
      <ConfirmDialog
        open={open}
        title="Return the report to the writer"
        confirmLabel="Return"
        cancelLabel="Cancel"
        busy={busy}
        confirmDisabled={!note.trim()}
        onConfirm={sendReturn}
        onCancel={() => {
          send.reset();
          setOpen(false);
        }}
      >
        {send.error ? <ErrorMessage error={send.error} /> : null}
        <p className="muted">The note becomes guidance for the revised report.</p>
        {note.trim() ? null : <p className="muted">A note is required.</p>}
        <div className="field">
          <label htmlFor={noteId}>Note for the writer</label>
          <textarea
            id={noteId}
            rows={4}
            value={note}
            dir="auto"
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      </ConfirmDialog>
    </div>
  );
}
```

Create `web/src/pages/review/ReviewBanner.tsx` (R-M18-12):

```tsx
import { Link } from "react-router";
import { rerunFreed, rerunPending } from "../../api/runs";
import type { ReviewState } from "../../api/types";
import { formatDateTime } from "../../lib/format";
import { degradationText, plural } from "../../lib/words";

/** Why a returned report can be returned again (R-M15-4), in the reader's words. */
export function revisionOutcome(review: ReviewState): string {
  switch (review.child_state) {
    case "cancelled":
      return "The revised report was stopped; return the report again or accept it.";
    case "gate_rejected":
      return "The revised report stopped at the value check (not supported by the sources); return the report again or accept it.";
    default:
      return `The revised report couldn't be written: ${review.child_error ?? "no reason was recorded"}. Return the report again or accept it.`;
  }
}

function Revised({ review }: { review: ReviewState }) {
  if (!review.child_run_id) return null;
  return <Link to={`/runs/${review.child_run_id}`}>Open the revised report</Link>;
}

/** M18 spec §5.4's banner: one sentence on where the review stands, and the one thing to do
 * next. A decision decides it; without one, a stage delivered without, then the standards not
 * met, then a clean report (R-M18-12). */
export function ReviewBanner({
  review,
  open,
  degradations,
  onShowStandards,
}: {
  review: ReviewState | null;
  open: number;
  degradations: string[];
  onShowStandards: () => void;
}) {
  let body;
  if (review?.decision === "accepted") {
    const by = review.actor ? ` by ${review.actor}` : "";
    body = (
      <p>
        Accepted{by} on {formatDateTime(review.at)}.
      </p>
    );
  } else if (review && rerunFreed(review)) {
    body = (
      <>
        <p dir="auto">Returned with a note. {revisionOutcome(review)}</p>
        <Revised review={review} />
      </>
    );
  } else if (review) {
    body = (
      <>
        <p>
          Returned with a note.
          {rerunPending(review) ? " The revised report is being written." : ""}
        </p>
        <Revised review={review} />
      </>
    );
  } else if (degradations.length > 0) {
    const lines = degradations.map(degradationText);
    const details = lines.flatMap((line) => (line.detail ? [line.detail] : []));
    body = (
      <>
        <p dir="auto">Delivered without a full check. {lines.map((l) => l.text).join(" ")}</p>
        {details.length > 0 ? (
          <details>
            <summary>Details</summary>
            <ul>
              {details.map((detail, i) => (
                <li key={i} dir="auto">
                  {detail}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </>
    );
  } else if (open > 0) {
    body = (
      <>
        <p>Ready to review. {plural(open, "standard")} not met.</p>
        <button type="button" className="link" onClick={onShowStandards}>
          Show them
        </button>
      </>
    );
  } else {
    body = <p>Ready to review. Every standard that could be checked was met.</p>;
  }
  return (
    <section role="status" aria-label="Where the review stands" className="banner row">
      {body}
    </section>
  );
}
```

Replace `web/src/pages/review/ReviewPage.tsx`:

```tsx
import { Link, useParams, useSearchParams } from "react-router";
import { useProjects } from "../../api/projects";
import { useReportHtml, useReportJson } from "../../api/reports";
import { useRun } from "../../api/runs";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useActiveProject, useDocumentTitle } from "../../components/frame";
import { Loading } from "../../components/Loading";
import { StatusText } from "../../components/StatusText";
import { Tabs } from "../../components/Tabs";
import { reportStatus } from "../../lib/status";
import { AuditTab } from "./AuditTab";
import { ProcessTab } from "./ProcessTab";
import { ProvenanceTab } from "./ProvenanceTab";
import { ReportFrame } from "./ReportFrame";
import { ReviewActions } from "./ReviewActions";
import { ReviewBanner } from "./ReviewBanner";
import { SourcesTab } from "./SourcesTab";

/** The tab ids stay those of M4b (they are in links); the labels are the reader's (§5.4). */
const TABS = [
  { id: "provenance", label: "Claims" },
  { id: "audit", label: "Standards" },
  { id: "process", label: "Process" },
  { id: "sources", label: "Sources" },
];

/** M18 spec §5.4. The selected claim and the open tab live in the URL. */
export function ReviewPage() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const claim = params.get("claim");
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "provenance";
  const run = useRun(runId);
  useActiveProject(run.data?.project_id ?? null);
  const projects = useProjects();
  const project = (projects.data ?? []).find((p) => p.id === run.data?.project_id);
  const completed = run.data?.state === "completed";
  const html = useReportHtml(runId, completed);
  const json = useReportJson(runId, completed);
  useDocumentTitle(json.data ? `${json.data.title} – Corelata` : null);

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  }

  if (run.isPending) return <Loading what="Loading the report" />;
  if (run.error) return <ErrorMessage error={run.error} />;
  if (!completed) {
    return (
      <section aria-label="No report">
        <p>This report has not been written yet.</p>
        <Link to={`/runs/${runId}`}>See its progress</Link>
      </section>
    );
  }
  const status = json.data?.metadata.status ?? run.data?.status;
  const open = json.data?.metadata.open_findings.length ?? 0;
  const degradations = json.data?.metadata.degradations ?? [];
  const review = run.data?.review ?? null;
  return (
    <article className="review">
      <header className="review-header">
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to={`/new?project=${run.data!.project_id}`}>{project?.name ?? "Project"}</Link>
        </nav>
        <div className="row between">
          <div className="row">
            <h1 dir="auto">{json.data?.title ?? "Report"}</h1>
            {status ? (
              <span className="pill">
                <StatusText status={reportStatus(status, open)} />
              </span>
            ) : null}
          </div>
          <ReviewActions runId={runId} review={review} />
        </div>
        {json.error ? <ErrorMessage error={json.error} /> : null}
      </header>
      <ReviewBanner
        review={review}
        open={open}
        degradations={degradations}
        onShowStandards={() => update({ tab: "audit" })}
      />
      <div className="review-body">
        <section aria-label="Report" className="report-pane">
          {html.isPending ? <Loading what="Preparing the report" /> : null}
          {html.error ? <ErrorMessage error={html.error} /> : null}
          {html.data ? (
            <ReportFrame
              html={html.data}
              selectedClaim={claim}
              onSelectClaim={(id) => update({ claim: id, tab: "provenance" })}
            />
          ) : null}
        </section>
        <aside className="side-pane" aria-label="Review details">
          <Tabs
            label="Review details"
            tabs={TABS}
            active={tab}
            onChange={(id) => update({ tab: id })}
          >
            {(active) => {
              switch (active) {
                case "audit":
                  return <AuditTab runId={runId} degradations={degradations} />;
                case "process":
                  return <ProcessTab runId={runId} />;
                case "sources":
                  return <SourcesTab runId={runId} />;
                default:
                  return (
                    <ProvenanceTab
                      runId={runId}
                      selectedClaim={claim}
                      onSelectClaim={(id) => update({ claim: id })}
                    />
                  );
              }
            }}
          </Tabs>
        </aside>
      </div>
    </article>
  );
}
```

Replace `web/src/pages/review/ProvenanceTab.tsx` (the Claims tab):

```tsx
import { useClaim, useReportJson } from "../../api/reports";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { CLAIM_KIND, citedByText, plural } from "../../lib/words";

/** The Claims tab (tab id `provenance`, M18 spec §5.4): the claims as rows, and the selected
 * claim's passages with where the report cites it. */
export function ProvenanceTab({
  runId,
  selectedClaim,
  onSelectClaim,
}: {
  runId: string;
  selectedClaim: string | null;
  onSelectClaim: (claimId: string) => void;
}) {
  const report = useReportJson(runId);
  const claim = useClaim(runId, selectedClaim);
  return (
    <div className="provenance">
      {report.isPending ? <Loading what="Loading claims" /> : null}
      {report.error ? <ErrorMessage error={report.error} /> : null}
      {report.data ? (
        <ul aria-label="Claims" className="claims">
          {report.data.claims.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="claim"
                aria-pressed={c.id === selectedClaim}
                onClick={() => onSelectClaim(c.id)}
              >
                <span className="claim-id">{c.id}</span>
                <span dir="auto">{c.text}</span>
                <span className="muted claim-meta">
                  {[
                    CLAIM_KIND[c.kind],
                    c.likelihood_term,
                    plural((c.evidence ?? []).length, "passage"),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {selectedClaim === null ? (
        <p className="muted">Select a claim, here or in the report, to see its evidence.</p>
      ) : null}
      {selectedClaim !== null && claim.isPending ? <Loading what="Loading evidence" /> : null}
      {claim.error ? <ErrorMessage error={claim.error} /> : null}
      {claim.data ? (
        <section aria-label={`Evidence for claim ${selectedClaim}`} className="evidence">
          <h3>Evidence for claim {selectedClaim}</h3>
          <ul aria-label={`Evidence for claim ${selectedClaim}`}>
            {claim.data.evidence.map((u) => (
              <li key={u.ref}>
                <p className="muted">
                  <span dir="auto">{u.source_name}</span> · {u.locator}
                </p>
                <blockquote dir="auto">{u.text}</blockquote>
              </li>
            ))}
          </ul>
          <p className="muted">Cited in: {claim.data.cited_by.map(citedByText).join("; ")}</p>
        </section>
      ) : null}
    </div>
  );
}
```

Replace `web/src/pages/review/AuditTab.tsx` (the Standards tab, R-M18-25):

```tsx
import { useResolvedPack } from "../../api/packs";
import { useFindings, useTrace } from "../../api/reports";
import type { Finding, Rule } from "../../api/types";
import { ErrorMessage } from "../../components/ErrorMessage";
import { Loading } from "../../components/Loading";
import { severityText, VERDICT } from "../../lib/words";

export type AuditRow = {
  ruleId: string;
  title: string;
  advisory: boolean;
  latest: Finding;
  history: Finding[]; // by iteration
};

/** One row per rule (spec §10.3 Audit tab): the last iteration's finding, with the history. */
export function auditRows(findings: Finding[], rules: Rule[] | undefined): AuditRow[] {
  const byRule = new Map<string, Finding[]>();
  for (const f of findings) byRule.set(f.rule_id, [...(byRule.get(f.rule_id) ?? []), f]);
  const ruleIndex = new Map((rules ?? []).map((r) => [r.id, r]));
  const order = (id: string) => {
    const i = (rules ?? []).findIndex((r) => r.id === id);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  return [...byRule.entries()]
    .sort(([a], [b]) => order(a) - order(b))
    .map(([ruleId, list]) => {
      const history = [...list].sort((a, b) => a.iteration - b.iteration);
      const rule = ruleIndex.get(ruleId);
      return {
        ruleId,
        title: rule?.title ?? ruleId,
        advisory: rule?.checkability === "advisory",
        latest: history.at(-1)!,
        history,
      };
    });
}

function verdictText(finding: Finding): string {
  const v = VERDICT[finding.verdict];
  return `${v.symbol} ${v.text}`;
}

/** M18 spec §5.4: one block per rule, not a table. */
function RuleGroup({ label, rows }: { label: string; rows: AuditRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section className="rule-group">
      <h3>{label}</h3>
      <ul aria-label={label} className="rules">
        {rows.map((r) => (
          <li key={r.ruleId} className="rule">
            <p className="rule-title">
              <strong dir="auto">{r.title}</strong>{" "}
              <span className="muted" dir="auto">
                {r.ruleId}
              </span>
            </p>
            <p className="row">
              <span className={`verdict verdict-${r.latest.verdict}`}>{verdictText(r.latest)}</span>
              <span className="muted">{severityText(r.latest.severity)}</span>
            </p>
            <details>
              <summary>Why</summary>
              <p dir="auto">{r.latest.evidence}</p>
              {r.latest.recommendation ? (
                <p className="muted" dir="auto">
                  {r.latest.recommendation}
                </p>
              ) : null}
            </details>
            {r.history.length > 1 ? (
              <p className="muted" aria-label="History">
                {r.history.map(verdictText).join(" → ")}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The Standards tab (tab id `audit`): Not met first, then Met and not applicable, then the
 * advisory rules (attested). */
export function AuditTab({ runId, degradations = [] }: { runId: string; degradations?: string[] }) {
  const findings = useFindings(runId);
  const trace = useTrace(runId);
  const summary = trace.data?.summary;
  const pack = useResolvedPack(summary?.pack_name ?? null, summary?.profile ?? null);
  const loadingTitles = trace.isPending || (pack.isPending && pack.fetchStatus === "fetching");
  if (findings.isPending) return <Loading what="Loading the standards check" />;
  if (findings.error) return <ErrorMessage error={findings.error} />;
  const rows = auditRows(findings.data ?? [], pack.data?.rules);
  const lastIteration = Math.max(-1, ...rows.map((r) => r.latest.iteration));
  const openNow = rows.filter(
    (r) => !r.advisory && r.latest.verdict === "fail" && r.latest.iteration === lastIteration,
  );
  // R-M11-2: "audit incomplete after N attempts: <reason>"; the rows shown are the previous check's
  const incomplete = degradations.find((d) => d.startsWith("audit incomplete"));
  const colon = incomplete?.indexOf(": ") ?? -1;
  const reason =
    incomplete !== undefined && colon !== -1 ? incomplete.slice(colon + 2) : incomplete;
  const checked = rows.filter((r) => !r.advisory);
  return (
    <div className="audit">
      {pack.error ? (
        <p className="muted">Rule titles are unavailable: {pack.error.message}</p>
      ) : null}
      {incomplete ? (
        <p className="notice" dir="auto">
          The standards check didn&apos;t finish: {reason}
        </p>
      ) : null}
      {rows.length === 0 && !incomplete ? (
        <p className="muted">No standards results were recorded.</p>
      ) : null}
      {rows.length > 0 && openNow.length === 0 && !incomplete ? (
        <p className="notice">Every standard that could be checked was met.</p>
      ) : null}
      {loadingTitles ? (
        <Loading what="Loading rule titles" />
      ) : (
        <>
          <RuleGroup label="Not met" rows={checked.filter((r) => r.latest.verdict === "fail")} />
          <RuleGroup
            label="Met and not applicable"
            rows={checked.filter((r) => r.latest.verdict !== "fail")}
          />
          <RuleGroup label="Advisory" rows={rows.filter((r) => r.advisory)} />
        </>
      )}
    </div>
  );
}
```

```diff
diff --git a/web/src/pages/review/ProcessTab.tsx b/web/src/pages/review/ProcessTab.tsx
index adb1a02..c98406f 100644
--- a/web/src/pages/review/ProcessTab.tsx
+++ b/web/src/pages/review/ProcessTab.tsx
@@ -1,8 +1,9 @@
 import { useTrace } from "../../api/reports";
-import type { DraftChanges, RunState } from "../../api/types";
+import type { DraftChanges } from "../../api/types";
 import { ErrorMessage } from "../../components/ErrorMessage";
 import { Loading } from "../../components/Loading";
-import { formatDuration, formatInt, STATE_LABELS } from "../../lib/format";
+import { formatDuration, formatInt } from "../../lib/format";
+import { STEP_LABEL } from "../../lib/words";
 
 export function describeChanges(changes: DraftChanges | null): string {
   if (changes === null) return "first draft";
@@ -17,6 +18,13 @@ export function describeChanges(changes: DraftChanges | null): string {
   return parts.length ? parts.join("; ") : "no changes";
 }
 
+/** A stage in the reader's words with the engine's in brackets (M18 spec §4.4); a stage the
+ * app does not know stays as it is. */
+export function stageName(stage: string): string {
+  const word = (STEP_LABEL as Record<string, string | undefined>)[stage];
+  return word ? `${word} (${stage})` : stage;
+}
+
 export function ProcessTab({ runId }: { runId: string }) {
   const trace = useTrace(runId);
   if (trace.isPending) return <Loading what="Loading the trace" />;
@@ -37,7 +45,7 @@ export function ProcessTab({ runId }: { runId: string }) {
         <tbody>
           {summary.stages.map((s, i) => (
             <tr key={i}>
-              <td>{STATE_LABELS[s.stage as RunState] ?? s.stage}</td>
+              <td>{stageName(s.stage)}</td>
               <td>{s.iteration}</td>
               <td>{formatDuration(s.duration_ms)}</td>
               <td>{s.ok ? "ok" : <span className="error">{s.error ?? "failed"}</span>}</td>
```

```diff
diff --git a/web/src/pages/review/SourcesTab.tsx b/web/src/pages/review/SourcesTab.tsx
index fedd863..3dabe37 100644
--- a/web/src/pages/review/SourcesTab.tsx
+++ b/web/src/pages/review/SourcesTab.tsx
@@ -10,8 +10,8 @@ export function SourcesTab({ runId }: { runId: string }) {
   return (
     <div className="sources-tab">
       <p className="muted">
-        Pack {summary.pack_name}
-        {summary.profile ? ` · profile ${summary.profile}` : ""} · {summary.pack_hash.slice(0, 12)}
+        Standards pack {summary.pack_name} ({summary.pack_hash.slice(0, 12)})
+        {summary.profile ? `, team profile ${summary.profile}` : ""}
       </p>
       <table aria-label="Sources">
         <thead>
@@ -40,7 +40,7 @@ export function SourcesTab({ runId }: { runId: string }) {
               <td>
                 {s.units} unit{s.units === 1 ? "" : "s"}
               </td>
-              <td>{s.digested ? "digested" : ""}</td>
+              <td>{s.digested ? "summarised before drafting" : ""}</td>
             </tr>
           ))}
         </tbody>
```

Replace `web/src/styles/review.css`:

```css
/* Review (spec §5.4): the header row, the banner, the report frame and the tabs beside it. */
.review {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.review-header h1 {
  margin: 0;
}

.pill {
  display: inline-flex;
  padding: var(--space-1) var(--space-3);
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-2);
  background: var(--surface-2);
}

.banner {
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-2);
  background: var(--surface-2);
}

.banner p {
  margin: 0;
}

.review-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--review-side-width);
  gap: var(--space-4);
  align-items: start;
}

/* The report keeps its own stylesheet inside the frame; the app's surface shows behind it, in
   either theme (R-M18-2). */
.report-frame {
  width: 100%;
  height: calc(100vh - var(--topbar-height) - 14rem);
  min-height: var(--frame-min-height);
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-2);
  background: var(--surface);
}

.side-pane {
  min-width: 0;
}

.tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: var(--border-width) solid var(--border);
}

.tabs [role="tab"] {
  border: 0;
  border-bottom: 0.1875rem solid transparent;
  border-radius: 0;
  background: transparent;
}

.tabs [role="tab"][aria-selected="true"] {
  border-bottom-color: var(--accent);
  font-weight: 600;
}

.tabpanel {
  padding: var(--space-3) 0;
}

.claims,
.rules {
  list-style: none;
  margin: 0;
  padding: 0;
}

.claims .claim {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  text-align: start;
  border: var(--border-width) solid transparent;
  background: transparent;
}

.claims .claim:hover {
  background: var(--surface-2);
}

.claims .claim[aria-pressed="true"] {
  border-color: var(--accent);
  background: var(--selected);
}

.claim-id {
  font-size: var(--text-sm);
  font-weight: 600;
}

.claim-meta {
  font-size: var(--text-sm);
}

.evidence blockquote {
  margin: var(--space-1) 0 var(--space-3);
  padding-inline-start: var(--space-3);
  border-inline-start: 0.1875rem solid var(--border);
}

.rule {
  padding: var(--space-3) 0;
  border-bottom: var(--border-width) solid var(--border);
}

.rule p {
  margin: 0 0 var(--space-1);
}

.verdict-fail {
  color: var(--danger);
}

.verdict-pass {
  color: var(--ok);
}

.verdict-attested,
.verdict-not_applicable {
  color: var(--text-muted);
}

.process table,
.sources-tab table {
  font-size: var(--text-sm);
}

@media (max-width: 1099px) {
  .review-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
```

- [ ] **Step 6: Run the tests, lint and build**

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: clean; 372 passed in 52 files, coverage at least 95%. `frameBridge.test.ts` and `ReportFrame.test.tsx` pass with no edit; the pinned review tests ("accepts, then shows the server's decision and disables both actions", "a return whose rerun ended without a report offers both actions again", "an open Review page keeps reading the run while its rerun runs", "re-reads the run after a refused review", "a stale page whose report another reviewer accepted…") keep their assertions with the new names.

- [ ] **Step 7: Commit**

```bash
cat > "$SCRATCH/m18-task7-commit.txt" <<'EOF'
feat(web): Review header, banner, Download menu, Claims and Standards, report follows the theme (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/src/pages/review web/src/lib/status.ts web/src/lib/status.test.ts web/src/lib/words.ts web/src/lib/words.test.ts web/src/lib/format.ts web/src/lib/format.test.ts web/src/pages/new/NewRunPage.test.tsx web/src/test/engine-words.ts web/src/styles/review.css
git -C "$REPO" commit -F "$SCRATCH/m18-task7-commit.txt"
```

---

### Task 8: Settings (spec §5.6)

**Files:**
- Create: `web/src/settings/SettingsPage.tsx`, `SettingsPage.test.tsx`, `statusSentence.ts`, `statusSentence.test.ts`, `TechnicalDetails.tsx`
- Modify: `web/src/api/system.ts`, `web/src/api/types.ts`, `web/src/routes.tsx`, `web/src/styles/base.css`, `web/src/test/fixtures.ts`

**Interfaces:**
- Consumes: Task 1's `useTheme`, `.card`; Task 4's `useDocumentTitle`, `plural`, the header's Settings link; `usePacks`, `useInfo` (unchanged).
- Produces: `useDoctorStatus()` (query, `probe=false`, key `["system", "doctor"]`), `useDoctor()` (mutation, `probe=true`); `DoctorReport`, `DoctorCheck` types; `statusSentence(report)`, `reportFailed(report)`; `SettingsPage`; the `/settings` route; the `doctorReport` fixture.

- [ ] **Step 1: Write the failing tests**

Create `web/src/settings/statusSentence.test.ts`:

```ts
import type { DoctorCheck } from "../api/types";
import { reportFailed, statusSentence } from "./statusSentence";

const check = (name: string, status: DoctorCheck["status"], message = "m"): DoctorCheck => ({
  name,
  status,
  message,
  fix: "",
});
const say = (...checks: DoctorCheck[]) => statusSentence({ checks, ok: true });

it("says everything is working, and how many notes wait under Technical details", () => {
  expect(say(check("config", "pass"))).toBe("Everything is working.");
  expect(say(check("config", "warn"))).toBe(
    "Everything is working. 1 note is under Technical details.",
  );
  expect(say(check("config", "warn"), check("pack", "warn"))).toBe(
    "Everything is working. 2 notes are under Technical details.",
  );
});

it.each([
  [
    "database",
    "Corelata can't reach its database. Reports can't start until an administrator fixes it.",
  ],
  [
    "backends",
    "Corelata can't reach a model server (backends). Reports can't be written until an administrator fixes it.",
  ],
  [
    "backend local",
    "Corelata can't reach a model server (backend local). Reports can't be written until an administrator fixes it.",
  ],
  [
    "model m1 auditor schema",
    "Corelata can't reach a model server (model m1 auditor schema). Reports can't be written until an administrator fixes it.",
  ],
  [
    "storage",
    "Corelata can't store files. Uploads and reports fail until an administrator fixes it.",
  ],
  ["pack", "Something needs an administrator's attention: pack."],
])("words a failing %s check", (name, sentence) => {
  expect(say(check("prompts", "pass"), check(name, "fail"))).toBe(sentence);
});

it("quotes the configuration's problem, and lets the first failing check decide", () => {
  expect(say(check("config", "fail", "backends.local.base_url: must not contain a query."))).toBe(
    "The configuration has a problem: backends.local.base_url: must not contain a query.",
  );
  expect(say(check("storage", "fail"), check("database", "fail"))).toMatch(/^Corelata can't store/);
  expect(reportFailed({ checks: [check("x", "warn")], ok: true })).toBe(false);
  expect(reportFailed({ checks: [check("x", "fail")], ok: false })).toBe(true);
});
```

Create `web/src/settings/SettingsPage.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { deferred } from "../test/deferred";
import { doctorReport, info, packs } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";
import { resetThemeForTests } from "../theme/theme";

let probes: string[] = [];

beforeEach(() => {
  probes = [];
  localStorage.clear();
  resetThemeForTests();
  server.use(
    http.get("*/api/system/doctor", ({ request }) => {
      probes.push(new URL(request.url).searchParams.get("probe") ?? "");
      return HttpResponse.json(doctorReport);
    }),
    http.get("*/api/packs", () => HttpResponse.json(packs)),
  );
});

it("is linked from the header, names the tab and chooses the theme (copied)", async () => {
  const { user, router } = renderApp("/new");
  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(router.state.location.pathname).toBe("/settings");
  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(document.title).toBe("Settings – Corelata");
  expect(screen.getByRole("radio", { name: "Match my computer" })).toBeChecked();
  await user.click(screen.getByRole("radio", { name: "Dark" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("corelata.theme")).toBe("dark");
});

it("says how the installation is doing without test completions, and runs a full check when asked", async () => {
  const { user } = renderApp("/settings");
  const status = await screen.findByRole("region", { name: "Status" });
  expect(
    await within(status).findByText("Everything is working. 1 note is under Technical details."),
  ).toBeInTheDocument();
  const live = within(status).getByRole("status");
  expect(live).toBeEmptyDOMElement(); // the check on opening is not announced
  server.use(
    http.get("*/api/system/doctor", ({ request }) => {
      probes.push(new URL(request.url).searchParams.get("probe") ?? "");
      return HttpResponse.json({
        ok: false,
        checks: [{ name: "model m1", status: "fail", message: "404", fix: "" }],
      });
    }),
  );
  await user.click(within(status).getByRole("button", { name: "Run a full check" }));
  await waitFor(() =>
    expect(live).toHaveTextContent(
      "Corelata can't reach a model server (model m1). Reports can't be written until an administrator fixes it.",
    ),
  );
  expect(probes).toEqual(["false", "true"]);
  expect(screen.getByRole("table", { name: "Checks" })).toHaveTextContent("model m1");
});

it("says when the status cannot be read, and while and why a full check fails", async () => {
  const held = deferred();
  server.use(
    http.get("*/api/system/doctor", async ({ request }) => {
      if (new URL(request.url).searchParams.get("probe") !== "true") {
        return HttpResponse.json({ detail: "the database is unreachable" }, { status: 500 });
      }
      await held.promise;
      return HttpResponse.json({ detail: "the full check timed out" }, { status: 500 });
    }),
  );
  const { user } = renderApp("/settings");
  const status = await screen.findByRole("region", { name: "Status" });
  expect(await within(status).findByRole("alert")).toHaveTextContent("the database is unreachable");
  await user.click(within(status).getByRole("button", { name: "Run a full check" }));
  expect(await within(status).findByRole("button", { name: "Checking…" })).toBeDisabled();
  held.resolve();
  expect(await within(status).findByText("the full check timed out")).toBeInTheDocument();
  expect(within(status).getByRole("button", { name: "Run a full check" })).toBeEnabled();
});

it("keeps the technical details folded: version, sign-in, limits, packs and every check", async () => {
  server.use(
    http.get("*/api/system/info", () =>
      HttpResponse.json({ ...info, default_profile: "team-east", auth_mode: "trusted_header" }),
    ),
  );
  renderApp("/settings");
  const details = (await screen.findByText("Technical details")).closest("details")!;
  expect(details).not.toHaveAttribute("open");
  await waitFor(() => expect(details).toHaveTextContent("Version0.1.0"));
  expect(details).toHaveTextContent("Sign-inby the proxy (trusted_header)");
  expect(details).toHaveTextContent("Upload limit200 MB");
  expect(details).toHaveTextContent("Default standards packicd203-base");
  expect(details).toHaveTextContent("Default team profileteam-east");
  const list = await within(details).findByRole("list", { name: "Standards packs" });
  expect(list).toHaveTextContent("icd203-base 1.0: team-east, draft-west (draft)");
  expect(within(details).getByRole("table", { name: "Checks" })).toHaveTextContent(
    "run a full check to send a test completion",
  );
});

it("shows a pack that failed to load and a packs failure", async () => {
  server.use(
    http.get("*/api/packs", () =>
      HttpResponse.json([{ ...packs[0]!, profiles: [], error: "pack.yaml: bad" }]),
    ),
  );
  renderApp("/settings");
  expect(await screen.findByText("pack.yaml: bad", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Standards packs" })).toHaveTextContent(
    /^icd203-base 1\.0 pack\.yaml: bad$/,
  );
  server.use(
    http.get("*/api/packs", () => HttpResponse.json({ detail: "packs offline" }, { status: 400 })),
  );
  renderApp("/settings");
  expect((await screen.findAllByRole("alert")).at(-1)).toHaveTextContent("packs offline");
});
```

```diff
diff --git a/web/src/test/fixtures.ts b/web/src/test/fixtures.ts
index a140bcb..5bd8399 100644
--- a/web/src/test/fixtures.ts
+++ b/web/src/test/fixtures.ts
@@ -1,6 +1,7 @@
 import type {
   CandidateStatement,
   ClaimProvenance,
+  DoctorReport,
   DiscoveryView,
   Finding,
   PackSummary,
@@ -471,3 +472,18 @@ export const reportHtml = `<!DOCTYPE html><html lang="en"><head><meta charset="u
 <section><h2>Analysis</h2><p data-claim-ids="c1">The terminal doubles grain handling.<sup class="claim-ids">c1</sup></p>
 <p data-claim-ids="">A paragraph with no claim.</p></section>
 </article></body></html>`;
+
+/** `GET /api/system/doctor?probe=false` on an install with one note (M18 spec §5.6). */
+export const doctorReport: DoctorReport = {
+  ok: true,
+  checks: [
+    { name: "config", status: "pass", message: "/etc/corelata/corelata.yaml is valid", fix: "" },
+    {
+      name: "backend local",
+      status: "warn",
+      message: "skipped: probe=false",
+      fix: "run a full check to send a test completion",
+    },
+    { name: "database", status: "pass", message: "postgresql://corelata@db at 0006", fix: "" },
+  ],
+};
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/settings`
Expected: FAIL: `Failed to resolve import "./statusSentence"`; the page tests land on "Page not found".

- [ ] **Step 3: The doctor's hooks and the route**

Replace `web/src/api/system.ts`:

```ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { client, unwrap } from "./client";
import type { DoctorReport, SystemInfo } from "./types";

export const systemKeys = {
  info: ["system", "info"] as const,
  doctor: ["system", "doctor"] as const,
};

/** Who is calling, which version answers, and what the deployment offers (spec §10.1 info). */
export function useInfo() {
  return useQuery({
    queryKey: systemKeys.info,
    queryFn: ({ signal }) => unwrap<SystemInfo>(client.GET("/api/system/info", { signal })),
    staleTime: Infinity,
  });
}

/** Settings ▸ Status (M18 spec §5.6): the installation checks without test completions, read
 * when the page opens. Copied from Coglossa's useDoctorStatus. */
export function useDoctorStatus() {
  return useQuery({
    queryKey: systemKeys.doctor,
    queryFn: ({ signal }) =>
      unwrap<DoctorReport>(
        client.GET("/api/system/doctor", { params: { query: { probe: false } }, signal }),
      ),
  });
}

/** Settings ▸ Run a full check: the checks with a test completion per model (probe=true).
 * Copied from Coglossa's useDoctor. */
export function useDoctor() {
  return useMutation({
    mutationFn: () =>
      unwrap<DoctorReport>(
        client.GET("/api/system/doctor", { params: { query: { probe: true } } }),
      ),
  });
}
```

```diff
diff --git a/web/src/api/types.ts b/web/src/api/types.ts
index 86aa5b0..9b66b0b 100644
--- a/web/src/api/types.ts
+++ b/web/src/api/types.ts
@@ -3,6 +3,8 @@ import type { components } from "./schema";
 type S = components["schemas"];
 
 export type SystemInfo = S["SystemInfo"];
+export type DoctorReport = S["DoctorReport"];
+export type DoctorCheck = S["DoctorCheck"];
 export type ProjectView = S["ProjectView"];
 export type LatestRun = S["LatestRun"];
 export type SourceView = S["SourceView"];
```

```diff
diff --git a/web/src/routes.tsx b/web/src/routes.tsx
index 298f8c8..79788c9 100644
--- a/web/src/routes.tsx
+++ b/web/src/routes.tsx
@@ -5,6 +5,7 @@ import { RouteError } from "./components/RouteError";
 import { NewRunPage } from "./pages/new/NewRunPage";
 import { ReviewPage } from "./pages/review/ReviewPage";
 import { RunPage } from "./pages/run/RunPage";
+import { SettingsPage } from "./settings/SettingsPage";
 
 export const routes: RouteObject[] = [
   {
@@ -20,6 +21,7 @@ export const routes: RouteObject[] = [
           { path: "new", element: <NewRunPage /> },
           { path: "runs/:runId", element: <RunPage /> },
           { path: "runs/:runId/review", element: <ReviewPage /> },
+          { path: "settings", element: <SettingsPage /> },
           { path: "*", element: <NotFound /> },
         ],
       },
```

- [ ] **Step 4: The page (R-M18-8)**

Create `web/src/settings/statusSentence.ts` (adapted from `$COGLOSSA/web/src/settings/statusSentence.ts`):

```ts
import type { DoctorCheck, DoctorReport } from "../api/types";
import { plural } from "../lib/words";

/** A check whose failure means no report can be written: the model servers (R-M18-8). */
function modelServer(name: string): boolean {
  return name === "backends" || name.startsWith("backend ") || name.startsWith("model ");
}

function failedSentence(check: DoctorCheck): string {
  if (check.name === "database") {
    return "Corelata can't reach its database. Reports can't start until an administrator fixes it.";
  }
  if (modelServer(check.name)) {
    return `Corelata can't reach a model server (${check.name}). Reports can't be written until an administrator fixes it.`;
  }
  if (check.name === "storage") {
    return "Corelata can't store files. Uploads and reports fail until an administrator fixes it.";
  }
  if (check.name === "config") {
    return `The configuration has a problem: ${check.message.replace(/\.$/, "")}.`;
  }
  return `Something needs an administrator's attention: ${check.name}.`;
}

export function reportFailed(report: DoctorReport): boolean {
  return report.checks.some((c) => c.status === "fail");
}

/** Adapted from Coglossa's statusSentence (M18 spec §5.6): what the installation checks mean for
 * the reader, in one sentence; the first failing check decides it. */
export function statusSentence(report: DoctorReport): string {
  const failed = report.checks.find((c) => c.status === "fail");
  if (failed) return failedSentence(failed);
  const notes = report.checks.filter((c) => c.status === "warn").length;
  if (notes === 0) return "Everything is working.";
  return `Everything is working. ${plural(notes, "note")} ${notes === 1 ? "is" : "are"} under Technical details.`;
}
```

Create `web/src/settings/TechnicalDetails.tsx`:

```tsx
import { usePacks } from "../api/packs";
import { useInfo } from "../api/system";
import type { DoctorReport } from "../api/types";
import { ErrorMessage } from "../components/ErrorMessage";
import { Loading } from "../components/Loading";

function Checks({ report }: { report: DoctorReport | undefined }) {
  if (report === undefined) return null;
  return (
    <table aria-label="Checks">
      <thead>
        <tr>
          <th>Result</th>
          <th>Check</th>
          <th>Details</th>
          <th>What to do</th>
        </tr>
      </thead>
      <tbody>
        {report.checks.map((check, i) => (
          <tr key={`${check.name}-${i}`}>
            <td>{check.status}</td>
            <td>{check.name}</td>
            <td dir="auto">{check.message}</td>
            <td dir="auto">{check.fix}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Packs() {
  const packs = usePacks();
  if (packs.isPending) return <Loading what="Loading the standards packs" />;
  if (packs.isError) return <ErrorMessage error={packs.error} />;
  return (
    <ul aria-label="Standards packs">
      {packs.data.map((pack) => (
        <li key={pack.name}>
          {pack.name} {pack.version}
          {pack.error ? <span className="error"> {pack.error}</span> : null}
          {pack.profiles.length > 0 ? (
            <>
              {": "}
              {pack.profiles.map((p) => `${p.name}${p.draft ? " (draft)" : ""}`).join(", ")}
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Settings ▸ Technical details (M18 spec §5.6), folded: what an administrator asks for. */
export function TechnicalDetails({ report }: { report: DoctorReport | undefined }) {
  const info = useInfo();
  return (
    <details className="technical">
      <summary>Technical details</summary>
      {info.data ? (
        <dl className="facts">
          <dt>Version</dt>
          <dd>{info.data.version}</dd>
          <dt>Sign-in</dt>
          <dd>
            {info.data.auth_mode === "none"
              ? "none (auth.mode none)"
              : "by the proxy (trusted_header)"}
          </dd>
          <dt>Upload limit</dt>
          <dd>{info.data.max_upload_mb} MB</dd>
          <dt>Default standards pack</dt>
          <dd>{info.data.default_pack}</dd>
          <dt>Default team profile</dt>
          <dd>{info.data.default_profile ?? "none"}</dd>
        </dl>
      ) : null}
      <h3>Standards packs and team profiles</h3>
      <Packs />
      <h3>Installation checks</h3>
      <Checks report={report} />
    </details>
  );
}
```

Create `web/src/settings/SettingsPage.tsx` (Appearance copied from Coglossa; no admin split):

```tsx
import { useDoctor, useDoctorStatus } from "../api/system";
import type { DoctorReport } from "../api/types";
import { ErrorMessage } from "../components/ErrorMessage";
import { useDocumentTitle } from "../components/frame";
import { Loading } from "../components/Loading";
import { useTheme, type ThemeChoice } from "../theme/theme";
import { reportFailed, statusSentence } from "./statusSentence";
import { TechnicalDetails } from "./TechnicalDetails";

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Match my computer" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/** Copied from Coglossa's SettingsPage. */
function Appearance() {
  const { choice, setChoice } = useTheme();
  return (
    <fieldset className="appearance card">
      <legend>Appearance</legend>
      <p className="muted">Theme</p>
      {THEMES.map((t) => (
        <label key={t.value}>
          <input
            type="radio"
            name="theme"
            value={t.value}
            checked={choice === t.value}
            onChange={() => setChoice(t.value)}
          />{" "}
          {t.label}
        </label>
      ))}
    </fieldset>
  );
}

function Sentence({ report }: { report: DoctorReport }) {
  const failed = reportFailed(report);
  return (
    <p className={failed ? "tone-bad" : "tone-ok"}>
      <span aria-hidden="true">{failed ? "! " : "✓ "}</span>
      {statusSentence(report)}
    </p>
  );
}

/** M18 spec §5.6: Appearance, Status and Technical details, for everyone (Corelata has no
 * roles). The quick check (no test completions) runs when the page opens; the full one when
 * asked, and only its sentence is announced. */
export function SettingsPage() {
  useDocumentTitle("Settings – Corelata");
  const quick = useDoctorStatus();
  const full = useDoctor();
  const report = full.data ?? quick.data; // the newest check wins, in the sentence and the table
  return (
    <section className="settings">
      <h1>Settings</h1>
      <Appearance />
      <section aria-label="Status" className="card">
        <h2>Status</h2>
        {report === undefined && quick.isPending ? <Loading what="Checking" /> : null}
        {report === undefined && quick.isError ? <ErrorMessage error={quick.error} /> : null}
        {report && !full.data ? <Sentence report={report} /> : null}
        <div role="status">{full.data ? <Sentence report={full.data} /> : null}</div>
        <button type="button" disabled={full.isPending} onClick={() => full.mutate()}>
          {full.isPending ? "Checking…" : "Run a full check"}
        </button>
        {full.isError ? <ErrorMessage error={full.error} /> : null}
      </section>
      <TechnicalDetails report={report} />
    </section>
  );
}
```

```diff
diff --git a/web/src/styles/base.css b/web/src/styles/base.css
index bf7aae8..b1f9e15 100644
--- a/web/src/styles/base.css
+++ b/web/src/styles/base.css
@@ -1,7 +1,7 @@
 /* Copied from Coglossa's web/src/styles/base.css (spec §2.2): element defaults and shared
    classes, on the design values only. Divergences: a one-family font stack (§2.4); the Han
    :lang() rules, mark, pre.config, .signals and .history are dropped (Coglossa-only screens);
-   .card is Corelata's. */
+   .card and the Settings rules at the end are Corelata's. */
 *,
 *::before,
 *::after {
@@ -293,3 +293,26 @@ td {
 .card > h2 {
   font-size: var(--text-md);
 }
+
+/* Settings (spec §5.6): Corelata's, like .card. */
+.settings {
+  display: flex;
+  flex-direction: column;
+  gap: var(--space-4);
+  max-width: 60rem;
+}
+
+.appearance label {
+  display: block;
+  margin: var(--space-1) 0;
+}
+
+.facts {
+  display: grid;
+  grid-template-columns: max-content 1fr;
+  gap: var(--space-1) var(--space-4);
+}
+
+.facts dd {
+  margin: 0;
+}
```

- [ ] **Step 5: Run the tests, lint and build**

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: clean; 385 passed in 54 files, coverage at least 95%.

- [ ] **Step 6: Commit**

```bash
cat > "$SCRATCH/m18-task8-commit.txt" <<'EOF'
feat(web): Settings with Appearance, Status and Technical details (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/src/settings web/src/api/system.ts web/src/api/types.ts web/src/routes.tsx web/src/styles/base.css web/src/test/fixtures.ts
git -C "$REPO" commit -F "$SCRATCH/m18-task8-commit.txt"
```

---

### Task 9: The Playwright journeys, dark mode, the sample policy in both themes (spec §8.3)

**Files:**
- Create: `web/e2e/theme.spec.ts`
- Modify: `web/e2e/journey.spec.ts`, `web/e2e/app.spec.ts`, `web/e2e/csp.spec.ts`

**Interfaces:**
- Consumes: every screen's names from Tasks 4 to 8.
- Produces: the end-to-end proof of §8.3.

- [ ] **Step 1: Run today's journeys to see them fail on the new screens**

Run: `make e2e`
Expected: FAIL in `journey.spec.ts` (no "Add a file" field, no "Start" button) and `app.spec.ts` (no `contentinfo` landmark, no "Start a new run" link); `csp.spec.ts` passes.

- [ ] **Step 2: Rewrite the journeys**

Replace `web/e2e/journey.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test";

const PORT_TEXT = [
  "The port of Varna handles grain, containers and general cargo on Bulgaria's Black Sea coast.",
  "A second grain terminal is planned for 2027, doubling the port's grain handling capacity.",
  "Shippers expect waiting times at Varna to fall by a third once the terminal opens.",
].join("\n\n");

function watchRequests(page: Page, origin: string): string[] {
  const foreign: string[] = [];
  page.on("request", (request) => {
    if (!request.url().startsWith(origin)) foreign.push(request.url());
  });
  return foreign;
}

test("a new project, upload, suggest value, write, review, return and the revised report", async ({
  page,
  baseURL,
}) => {
  const foreign = watchRequests(page, baseURL!);
  await page.goto("/");
  await expect(page).toHaveURL(/\/new$/);
  await expect(page).toHaveTitle("New report – Corelata");

  // New report: a new project, then its page (M18 spec §5.1, §5.2).
  await page.getByRole("button", { name: "New project" }).click();
  const name = `Journey ${Date.now()}`;
  await page.getByRole("textbox", { name: "Project name" }).fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Your projects" })
      .getByRole("link", { name: new RegExp(`^${name}`) }),
  ).toHaveAttribute("aria-current", "page");
  await page.getByLabel("Choose files").setInputFiles({
    name: "port.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(PORT_TEXT, "utf-8"),
  });
  await expect(page.getByRole("list", { name: "Chosen files" })).toContainText("port.txt");
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("checkbox", { name: "Use port.txt in this report" })).toBeChecked();

  await page.getByRole("button", { name: "Suggest value" }).click();
  const suggestions = page.getByRole("list", { name: "Suggested value statements" });
  await expect(suggestions).toBeVisible();
  // the suggestions are in the URL: a reload reads them again (R-M16-14)
  await expect(page).toHaveURL(/[?&]discovery=[0-9a-f-]+/);
  await page.reload();
  await expect(suggestions).toBeVisible();
  await suggestions.getByRole("button", { name: "Use this statement" }).first().click();
  await expect(page.getByRole("textbox", { name: "Value statement" })).not.toHaveValue("");
  await page.getByText("More options").click();
  await page.getByRole("spinbutton", { name: "Revision rounds" }).fill("1");
  await page.getByRole("button", { name: "Write the report" }).click();

  // Writing the report: the steps reach Ready to review (§5.3).
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  const review = page.getByRole("link", { name: "Review the report" });
  await expect(review).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("heading", { name: "Ready to review." })).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Steps" }).locator('[data-status="done"]'),
  ).toHaveCount(8);
  await expect(page).toHaveTitle(/^✓ Ready to review – /);
  await page.getByText("Details", { exact: true }).click();
  await expect(page.getByRole("status", { name: "Token usage" })).toContainText("model calls");
  await review.click();

  // Review: the report, its claims and evidence, the tabs, the downloads (§5.4).
  await expect(page).toHaveURL(/\/review$/);
  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  const claims = page.getByRole("list", { name: "Claims" });
  await claims.getByRole("button").first().click();
  await expect(page.getByRole("list", { name: /^Evidence for claim / })).toBeVisible();
  await expect(frame.locator(".corelata-highlight").first()).toBeVisible();
  // a click on a cited element inside the real frame reaches the page through the bridge
  await page.getByRole("tab", { name: "Standards" }).click();
  await frame.locator("[data-claim-ids]:not([data-claim-ids=''])").first().click();
  await expect(page).toHaveURL(/claim=/);
  await expect(page.getByRole("tab", { name: "Claims" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Standards" }).click();
  await expect(page.getByRole("tabpanel").locator(".rule").first()).toBeVisible();
  await page.getByRole("tab", { name: "Process" }).click();
  await expect(page.getByRole("table", { name: "Stage timeline" })).toBeVisible();
  await page.getByRole("tab", { name: "Sources" }).click();
  await expect(page.getByRole("table", { name: "Sources" })).toContainText("port.txt");

  await page.getByRole("button", { name: "Download" }).click();
  const items = page.getByRole("menu", { name: "Download" }).getByRole("menuitem");
  await expect(items).toHaveText([
    "Word document (DOCX)",
    "Markdown",
    "Web page (HTML)",
    "Trace (JSON)",
  ]);
  const types = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/html",
    "application/json",
  ];
  for (const [i, type] of types.entries()) {
    const href = await items.nth(i).getAttribute("href");
    const response = await page.request.get(href!);
    expect(response.status(), type).toBe(200);
    expect(response.headers()["content-type"], type).toContain(type);
  }
  await page.keyboard.press("Escape");

  // Return with note: a revised report is written (§5.4).
  await page.getByRole("button", { name: "Return with note…" }).click();
  await page
    .getByRole("textbox", { name: "Note for the writer" })
    .fill("Add the 2027 date to the title.");
  await page.getByRole("button", { name: "Return", exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(page.getByRole("link", { name: "Review the report" })).toBeVisible({
    timeout: 90_000,
  });

  expect(foreign, "every request stayed on the app's origin").toEqual([]);
});

test("a reload keeps the project, the tab and the selected claim", async ({ page }) => {
  await page.goto("/new");
  const picker = page.getByRole("combobox", { name: "Project" });
  await picker.selectOption({ index: 1 });
  await expect(page).toHaveURL(/\?project=/);
  const heading = page.getByRole("main").getByRole("heading", { level: 1 });
  const name = await heading.textContent();
  await page.reload();
  await expect(heading).toHaveText(name!);
  await page
    .getByRole("list", { name: "Reports" })
    .getByRole("link", { name: "Review" })
    .first()
    .click();
  const claims = page.getByRole("list", { name: "Claims" });
  await claims.getByRole("button").first().click();
  await expect(page).toHaveURL(/claim=/);
  await expect(claims.getByRole("button").first()).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("tab", { name: "Sources" }).click();
  await page.reload();
  await expect(page.getByRole("tab", { name: "Sources" })).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/claim=/);
  await page.getByRole("tab", { name: "Claims" }).click();
  await expect(claims.getByRole("button").first()).toHaveAttribute("aria-pressed", "true");
});
```

Replace `web/e2e/app.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("an unknown address shows the app's not-found page", async ({ page }) => {
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Start a new report" }).click();
  await expect(page).toHaveURL(/\/new$/);
});

test("unknown API paths answer JSON 404, not the app", async ({ request }) => {
  const response = await request.get("/api/nope");
  expect(response.status()).toBe(404);
  expect(await response.json()).toEqual({ detail: "Not Found" });
});

// The version moved from the page footer to the sidebar's foot (M18 spec §3.3); a <footer>
// inside <nav> is not a contentinfo landmark, so it is found by its text.
test("the sidebar's foot shows the version from the API", async ({ page, request }) => {
  const health = await (await request.get("/api/health")).json();
  await page.goto("/new");
  await expect(
    page.getByRole("navigation", { name: "Your projects" }).getByText(`Corelata ${health.version}`),
  ).toBeVisible();
});
```

Create `web/e2e/theme.spec.ts` (Review Focus 1):

```ts
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// M18 spec §8.3: dark mode before the first paint, on every screen, and inside the report frame,
// which follows the app's theme rather than the computer's (R-M18-2).

const PORT_TEXT = [
  "The port of Varna handles grain, containers and general cargo on Bulgaria's Black Sea coast.",
  "A second grain terminal is planned for 2027, doubling the port's grain handling capacity.",
  "Shippers expect waiting times at Varna to fall by a third once the terminal opens.",
].join("\n\n");

/** A project with one source and a run of it; returns their ids. */
async function startRun(request: APIRequestContext) {
  const project = await request.post("/api/projects", { data: { name: `Theme ${Date.now()}` } });
  expect(project.status()).toBe(201);
  const projectId: string = (await project.json()).id;
  const upload = await request.post(`/api/projects/${projectId}/sources`, {
    multipart: {
      file: { name: "port.txt", mimeType: "text/plain", buffer: Buffer.from(PORT_TEXT, "utf-8") },
    },
  });
  const [source] = await upload.json();
  const run = await request.post("/api/runs", {
    data: {
      project_id: projectId,
      source_ids: [source.id],
      value_statement: "Varna port capacity expansion matters to shippers",
      max_iterations: 0,
    },
  });
  expect(run.status()).toBe(202);
  return { projectId, runId: (await run.json()).run_id as string };
}

/** Stores the theme before the app loads, and records data-theme when <body> is first parsed:
 * theme-init.js must have set it by then, so the first paint is already in that theme. */
async function chooseTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((choice) => {
    localStorage.setItem("corelata.theme", choice);
    new MutationObserver((_, observer) => {
      if (!document.body) return;
      (window as unknown as { themeAtBody?: string }).themeAtBody =
        document.documentElement.dataset.theme;
      observer.disconnect();
    }).observe(document, { childList: true, subtree: true });
  }, theme);
}

const DARK_BG = "rgb(21, 23, 28)"; // --bg, dark
const DARK_SURFACE = "rgb(27, 30, 37)"; // --surface, dark

test("a stored dark theme applies before the first paint, on every screen and in the report", async ({
  page,
  request,
}) => {
  await chooseTheme(page, "dark"); // the computer stays light: Chromium's default
  const { projectId, runId } = await startRun(request);
  for (const path of ["/new", `/new?project=${projectId}`, `/runs/${runId}`, "/settings"]) {
    await page.goto(path);
    expect(
      await page.evaluate(() => (window as unknown as { themeAtBody?: string }).themeAtBody),
    ).toBe("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);
  }
  await page.goto(`/runs/${runId}`);
  await page.getByRole("link", { name: "Review the report" }).click({ timeout: 90_000 });
  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  await expect(frame.locator("html")).toHaveClass("corelata-theme-dark");
  await expect(frame.locator("body")).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(page.locator('iframe[title="Report"]')).toHaveCSS("background-color", DARK_SURFACE);
  // the toggle switches the report too, without reloading it
  await page.getByRole("button", { name: "Switch to the light theme" }).click();
  await expect(frame.locator("html")).toHaveClass("corelata-theme-light");
  await expect(frame.locator("body")).toHaveCSS("color", "rgb(0, 0, 0)");
});

test("a light app on a dark computer shows the report light", async ({ page, request }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await chooseTheme(page, "light");
  const { runId } = await startRun(request);
  await page.goto(`/runs/${runId}`);
  await page.getByRole("link", { name: "Review the report" }).click({ timeout: 90_000 });
  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(frame.locator("html")).toHaveClass("corelata-theme-light");
  await expect(frame.locator("body")).toHaveCSS("color", "rgb(0, 0, 0)");
});
```

The sample policy in both themes (Review Focus 2; what it checks is unchanged):

```diff
diff --git a/web/e2e/csp.spec.ts b/web/e2e/csp.spec.ts
index 65509eb..397a06d 100644
--- a/web/e2e/csp.spec.ts
+++ b/web/e2e/csp.spec.ts
@@ -13,61 +13,68 @@ const PORT_TEXT = [
 ].join("\n\n");
 const STATEMENT = "Varna port capacity expansion matters to shippers";
 
-test("a run, its progress and the claim highlight work under the guide's sample policy", async ({
-  page,
-  request,
-}) => {
-  expect(SAMPLE, "the guide's sample policy").toBeTruthy();
-  const violations: string[] = [];
-  page.on("console", (message) => {
-    if (/Content Security Policy|Refused to|CSP violation/i.test(message.text()))
-      violations.push(message.text());
-  });
-  await page.addInitScript(() => {
-    document.addEventListener("securitypolicyviolation", (event) =>
-      console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`),
-    );
-  });
+// In both themes (M18 spec §8.3): the theme script is a file, and the frame's theme classes
+// are in the bridge's nonce-bound style, so the sample policy allows both.
+for (const theme of ["light", "dark"] as const) {
+  test(`a run, its progress and the claim highlight work under the guide's sample policy (${theme})`, async ({
+    page,
+    request,
+  }) => {
+    expect(SAMPLE, "the guide's sample policy").toBeTruthy();
+    await page.addInitScript((choice) => localStorage.setItem("corelata.theme", choice), theme);
+    const violations: string[] = [];
+    page.on("console", (message) => {
+      if (/Content Security Policy|Refused to|CSP violation/i.test(message.text()))
+        violations.push(message.text());
+    });
+    await page.addInitScript(() => {
+      document.addEventListener("securitypolicyviolation", (event) =>
+        console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`),
+      );
+    });
 
-  const home = await page.goto("/new");
-  expect(home?.headers()["content-security-policy"]).toBe(SAMPLE);
+    const home = await page.goto("/new");
+    expect(home?.headers()["content-security-policy"]).toBe(SAMPLE);
 
-  const project = await request.post("/api/projects", { data: { name: `CSP ${Date.now()}` } });
-  expect(project.status()).toBe(201);
-  const projectId: string = (await project.json()).id;
-  const upload = await request.post(`/api/projects/${projectId}/sources`, {
-    multipart: {
-      file: { name: "port.txt", mimeType: "text/plain", buffer: Buffer.from(PORT_TEXT, "utf-8") },
-    },
-  });
-  expect(upload.status()).toBe(201);
-  const [source] = await upload.json();
-  const run = await request.post("/api/runs", {
-    data: {
-      project_id: projectId,
-      source_ids: [source.id],
-      value_statement: STATEMENT,
-      max_iterations: 1,
-    },
-  });
-  expect(run.status()).toBe(202);
-  const runId: string = (await run.json()).run_id;
+    const project = await request.post("/api/projects", { data: { name: `CSP ${Date.now()}` } });
+    expect(project.status()).toBe(201);
+    const projectId: string = (await project.json()).id;
+    const upload = await request.post(`/api/projects/${projectId}/sources`, {
+      multipart: {
+        file: { name: "port.txt", mimeType: "text/plain", buffer: Buffer.from(PORT_TEXT, "utf-8") },
+      },
+    });
+    expect(upload.status()).toBe(201);
+    const [source] = await upload.json();
+    const run = await request.post("/api/runs", {
+      data: {
+        project_id: projectId,
+        source_ids: [source.id],
+        value_statement: STATEMENT,
+        max_iterations: 1,
+      },
+    });
+    expect(run.status()).toBe(202);
+    const runId: string = (await run.json()).run_id;
 
-  // Progress arrives over the event stream, through the proxy.
-  await page.goto(`/runs/${runId}`);
-  const review = page.getByRole("link", { name: "Review the report" });
-  await expect(review).toBeVisible({ timeout: 90_000 });
-  await review.click();
+    // Progress arrives over the event stream, through the proxy.
+    await page.goto(`/runs/${runId}`);
+    const review = page.getByRole("link", { name: "Review the report" });
+    await expect(review).toBeVisible({ timeout: 90_000 });
+    await review.click();
 
-  const frame = page.frameLocator('iframe[title="Report"]');
-  await expect(frame.locator("h1")).toBeVisible();
-  // The report's own stylesheet applied (allowed by its hash): 46rem at 16px.
-  await expect(frame.locator("body")).toHaveCSS("max-width", "736px");
-  await page.getByRole("list", { name: "Claims" }).getByRole("button").first().click();
-  // The bridge's highlight style applied (allowed by the nonce), on the claim the page chose.
-  await expect(frame.locator(".corelata-highlight").first()).toHaveCSS(
-    "background-color",
-    "rgb(255, 243, 176)",
-  );
-  expect(violations, "no Content-Security-Policy violation").toEqual([]);
-});
+    const frame = page.frameLocator('iframe[title="Report"]');
+    await expect(frame.locator("h1")).toBeVisible();
+    // The report's own stylesheet applied (allowed by its hash): 46rem at 16px.
+    await expect(frame.locator("body")).toHaveCSS("max-width", "736px");
+    await page.getByRole("list", { name: "Claims" }).getByRole("button").first().click();
+    // The bridge's highlight style applied (allowed by the nonce), on the claim the page chose.
+    await expect(frame.locator(".corelata-highlight").first()).toHaveCSS(
+      "background-color",
+      "rgb(255, 243, 176)",
+    );
+    await expect(frame.locator("html")).toHaveClass(`corelata-theme-${theme}`);
+    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
+    expect(violations, "no Content-Security-Policy violation").toEqual([]);
+  });
+}
```

- [ ] **Step 3: Run them**

Run: `make e2e`
Expected: 9 passed (6 before): app 3, journey 2, theme 2 in the `chromium` project; csp 2 in `csp-proxy`. Every request of the journey stayed on the app's origin.

Run: `cd web && pnpm lint`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cat > "$SCRATCH/m18-task9-commit.txt" <<'EOF'
test(e2e): journeys on the new screens, dark mode and the sample policy in both themes (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add web/e2e
git -C "$REPO" commit -F "$SCRATCH/m18-task9-commit.txt"
```

---

### Task 10: Docs

**Files:**
- Modify: `README.md` (a new M18 section before `## Development`), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§10.1, §10.3, §11), `docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md` (a §9.1 of amendments, §22's decisions taken), `docs/operator-guide.md` (§5, §6, §7, §11, §13)
- Create: `docs/m18-followups.md`

**Interfaces:**
- Consumes: the behaviour of Tasks 1 to 9 as their tests pin it (the words, the ruling numbers).
- Produces: documentation only.

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
## M18: Corelata on Coglossa's design system

CRL-41. Corelata's web app now looks and behaves like Coglossa's: the same colour tokens in a
light and a dark set, the same type (Noto Sans, `@fontsource/noto-sans` 5.3.0 as Coglossa ships
it, the one new package), buttons, header and sidebar. The theme follows the computer until
someone picks one (the header's ☾ / ☀, or Settings ▸ Appearance); it is set before the page
draws, and the report inside the review frame follows it too, with `report.css`, its hash and
the frame's policy unchanged. A sidebar lists the projects, newest activity first, grouped Today,
This week and Earlier, each with one status ("… writing", "● 2 to review", "! needs attention");
`GET /api/projects` carries what it needs (`last_activity_at`, `reports_writing`,
`reports_to_review`, `latest_run`), computed by three grouped statements however many projects
there are. The screens speak the reader's words: a run is a report, the gate is the value check,
the audit is the standards check; the engine's words stay in the Process and Sources tabs,
Settings ▸ Technical details, the API, the CLI and the trace. New report asks which project it
is for; the project page holds Sources (drop several files at once, as documents or Coglossa
exports, uploaded one after another), the value statement and its suggestions, More options
(team profile, revision rounds), Write the report and the Reports list (`GET /api/runs` rows
carry `review_decision` and `review_child_state`). Writing the report lists eight steps, each a
symbol and a word, with a Details fold and Stop writing…. Review has the title, a status pill,
Accept, Return with note… and a Download menu in its header, a one-sentence banner, and the report
beside the Claims, Standards (each rule a block: not met, met and not applicable, advisory),
Process and Sources tabs. Settings holds Appearance, the installation's status in one sentence
with a full check, and Technical details; Help (the header, or `?`) explains the keys, statuses
and steps. `auth.logout_url` adds Sign out to the header for a proxy with a sign-out page. Text
meets WCAG AA in both themes (a test checks every colour pair), no stylesheet but `tokens.css`
holds a raw colour, and the behaviour M9 to M17 pinned is unchanged.
```

- [ ] **Step 2: Spec amendments**

In `docs/superpowers/specs/2026-10-12-corelata-v1-design.md`:

After the §10.1 paragraph that starts `M17 amendments (CRL-38): \`GET /discoveries/{id}\``, add:

```markdown
M18 amendments (CRL-41): `ProjectView` (on `GET /projects`, `GET /projects/{id}` and
`POST /projects`) carries `last_activity_at` (the latest of the project's, its sources' and its
runs' stamps), `reports_writing`, `reports_to_review` (completed with no decision, or a return
whose rerun ended without a report) and `latest_run` (`{run_id, state, status, decision}`),
computed by three statements for the whole list. `RunSummary` carries `review_decision` and
`review_child_state` from the stored decision. `SystemInfo` carries `logout_url`. No new route.
```

At the end of §10.3 (after the paragraph that starts `M17 amendments: the New run screen keeps`), add:

```markdown
M18 amendments (CRL-41): the web app is on Coglossa's design system, specified in
`docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md` §2 to §9 and the
M18 plan's rulings. A header (theme toggle, Help, Settings, the signed-in name, Sign out when
`auth.logout_url` is set) and a project sidebar frame every screen. New run is New report
(`/new`, choose or create a project) and the project page (`/new?project=<id>&sources=&discovery=`,
the same URL state); Progress is Writing the report; Review's tabs keep their ids and read
Claims, Standards, Process and Sources; `/settings` is added (Appearance, Status from
`GET /system/doctor`, Technical details), which replaces "No System screen in v1". M17's
live-region text "Waiting for the worker to start the discovery…" reads "Waiting for Corelata
to start looking…"; "Looking for value in the selected sources…" and the 10-minute fallback are
unchanged. The report frame follows the app's theme by a class the bridge sets on the frame's
root, in its nonce-bound style; `report.css`, its hash and the frame's policy are unchanged.
```

In §11, after the paragraph that starts `M17 amendments: \`worker.discovery_deadline_s\``, add:

```markdown
M18 amendment: `auth.logout_url` (optional, operational, outside `config_hash`) is the
proxy's sign-out page; when it is set the web header shows Sign out, a POST to it.
```

In `docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md`, change the
status line `- **Status:** Draft for review` to `- **Status:** Part A planned (M18 plan,
2026-10-20); Part B for M19`, and add after §9:

```markdown
### 9.1 Amendments from the M18 plan

The plan (`docs/superpowers/plans/2026-10-20-m18-design-system.md`) took decisions 22.1 and 22.6
as recommended (R-M18-1, R-M18-2) and settled what this part left open:

- §3.3's last row shows the latest report's own status from §4.2 (R-M18-6).
- §7.2: `RunSummary` also carries `review_child_state`, so the Reports list shows a return whose
  revision ended without a report as "to review", as the sidebar counts it (R-M18-7).
- §5.4: the clean banner reads "Ready to review. Every standard that could be checked was met.",
  without the pack word §4.1 keeps to the Sources tab and Settings; a decision decides the banner
  before a degradation, open standards or a clean report (R-M18-12).
- §5.5: the frame is built in the page's theme and told only when the theme changes, or when a
  reloaded frame's theme differs, so it never shows the computer's theme first (R-M18-10).
- §5.6: `backend <name>` failures read as a model server's too (R-M18-8).
- §7.1: the newest run is a `DISTINCT ON` statement written out in SQL (R-M18-17).
- §7.4: the route test already lists Settings' routes; no edit (R-M18-22).
- §2.2: `Menu.tsx` carries one lint suppression (Corelata keeps `react-hooks/refs` on), and
  Coglossa's `test/jsdom-storage.ts` is copied too, for Node 25 and later (R-M18-9, R-M18-16).
- The words the tables do not give are R-M18-13's.
```

In §22, after the line `Each has a recommendation; everything else in this spec is decided.`, add `Taken 2026-10-20 for M18: 1 (Noto Sans) and 6 (the report follows the app's theme), as recommended. 2 to 5 belong to M19.`

- [ ] **Step 3: The operator guide**

Make these edits in `docs/operator-guide.md` (each old text occurs once):

| Section | Old | New |
|---|---|---|
| §5 Standards packs | `New run screen that is already open keeps the list it loaded` | `project page that is already open keeps the list it loaded` |
| §5 Uploads and the API | `discovery waits, the New run screen says "Waiting for the worker to start the discovery…"; once` | `discovery waits, the project page says "Waiting for Corelata to start looking…"; once` |
| §7 | `The web app offers the same downloads on a run's page.` | `The web app offers the same downloads in the review's **Download** menu.` |
| §7 | `` An accept is final: `review --return` (or **Return with note**) on an accepted run is refused `` | `` An accept is final: `review --return` (or **Return with note…**) on an accepted run is refused `` |
| §7 | `` **Cancelling a run whose worker died.** A cancel (`corelata cancel <run-id>`, or **Cancel run**) `` | `` **Cancelling a run whose worker died.** A cancel (`corelata cancel <run-id>`, or **Stop writing…**) `` |
| §7 | `on the screen the **Cancel run** button is replaced by the text "Stopping after the current` and, on the next line, `stage…".` | `on the screen the **Stop writing…** button is replaced by the text "Stopping after the current` and `step…".` |
| §11 | `` | The Review screen says "The rerun failed: …" (or was cancelled, or stopped at the gate) | `` | `` | The review says "The revised report couldn't be written: …" (or was stopped, or stopped at the value check) | `` |
| §11 | `then use **Return with note** again (the previous note is offered)` | `then use **Return with note…** again (the previous note is offered)` |
| §11 | `` | The New run screen says "Discovery did not start `` | `` | The project page says "Discovery did not start `` |
| §11 | `` | The New run screen says "Discovery did not finish `` | `` | The project page says "Discovery did not finish `` |
| §11 | `` | The New run screen says "Discovery has not finished `` | `` | The project page says "Discovery has not finished `` |
| §11 | `` | A run says "Stopping after the current stage…" and does not move | `` | `` | A report says "Stopping after the current step…" and does not move | `` |
| §11 | `(the review screen shows the same notice)` | `(the review's banner says "Delivered without a full check" and names the step)` |
| §13 | `` `GET /api/health`, the footer `` and, on the next line, `of the web app and` | `` `GET /api/health`, the foot of `` and `the web app's sidebar, Settings ▸ Technical details and` |

In §6, after the paragraph that ends `overwriting anything the client sent.`, add:

````markdown
If the proxy has a sign-out address that ends its session when it receives a POST, tell
Corelata where it is and the header shows **Sign out**, a form that posts there:

```yaml
auth: { mode: trusted_header, header: X-Remote-User, logout_url: /oauth2/sign_out }
```

It is operational (not part of `config_hash`, so runs are unaffected); apply it as in section 5,
"Applying changes". Without it no Sign out is shown, which is right for basic authentication,
where the browser keeps the password until it is closed.
````

In §7, before `**The HTTP API.**`, add:

```markdown
**The web app.** Every screen has a header (the name, which leads to New report; the theme
toggle ☾ / ☀; **Help**, also on `?`; **Settings**; the signed-in name and **Sign out** when the
proxy provides them) and a sidebar: **+ New report**, then the projects, newest activity first,
grouped Today, This week and Earlier, each with one status: "… writing", "● N to review",
"! needs attention" (its latest report could not be written), "⚠ not supported", "✓ accepted",
"■ stopped", or "no reports yet". The sidebar's foot shows the version. Below 900 px wide the
sidebar opens from the header's **Your projects**. **New report** asks which project the report
is for, or creates one. A project's page holds its **Sources** (drop files or click to choose;
**Add as** documents or Coglossa exports; a file over `api.max_upload_mb` or of another type is
marked and not sent; **Upload** sends the others one after another), the **Value statement**
with **Suggest value**, **More options** (team profile, revision rounds), **Write the report**,
and the project's **Reports**. **Writing the report** lists the steps, each with ✓ done, ● now,
! failed or ○ not yet; **Details** holds each step's duration and error and the model usage; the
page can be left while it writes. The review shows the report beside four tabs: **Claims** (a
claim's passages and where the report cites it), **Standards** (each rule: not met, met and not
applicable, advisory, with why and its history), **Process** and **Sources** (the stages, models
and hashes, in the engine's words); **Accept**, **Return with note…** and **Download** are in its
header. **Settings** has the theme, the installation's status in one sentence (**Run a full
check** sends a test completion to each model) and **Technical details** (version, sign-in mode,
upload limit, default pack and team profile, the packs and their profiles, every check). The
theme follows the computer until someone picks one, per browser.
```

- [ ] **Step 4: Follow-ups**

Create `docs/m18-followups.md`:

```markdown
# M18 follow-ups

## Divergences from Coglossa

- `tokens.css`: two layout tokens added (`--review-side-width`, `--frame-min-height`); colours
  unchanged.
- `base.css`: a one-family font stack (Noto Sans, then the computer's fonts); the Han `:lang()`
  rules, `mark`, `pre.config`, `.signals` and `.history` dropped (Coglossa-only screens); `.card`
  and the Settings rules (`.settings`, `.appearance`, `.facts`) added.
- `shell.css`: `.project-row`, `.project-link` (current page by `aria-current`), `.project-name`;
  no `.row-menu`; `.sidebar-foot` for the version.
- `theme-init.js`, `theme.ts`: the key `corelata.theme`.
- `contrast.test.ts`: the frame's highlight pair (`#1a1a1a` on `#fff3b0`) added — **backport
  candidate**: Coglossa has no in-frame colours yet.
- `logical-edges.test.ts` not copied (no flagged-passage bar).
- `test/jsdom-storage.ts` copied, called from Corelata's own `jsdom-env.ts`.
- `fonts.ts`, `fonts.test.ts`: one family.
- `Menu.tsx`: one `eslint-disable-next-line react-hooks/refs`; Corelata keeps the rule on, which
  Coglossa turns off app-wide (R-M18-9).
- `Dialog.tsx`, `StatusText.tsx`, `dates.ts`, `keys.ts`: unchanged but a header comment;
  `Dialog.test.tsx` is Corelata's (Coglossa tests it only through others).
- `Layout`: reads `GET /api/system/info` (Corelata has no `/api/me`); provides the active project
  to the sidebar through a context; the version moved from the page footer to the sidebar's foot,
  so M7's "the web footer reports the bundle version" still holds there.
- `Sidebar`: projects, Corelata's statuses (§3.3), no Rename or Delete (Corelata has neither
  route), no ⋯ menu.
- `HelpDialog`: Corelata's keys, statuses, steps and standards results.
- `SettingsPage`: no admin split (Corelata has no roles); Status from Corelata's doctor checks;
  Technical details without Coglossa's score search, configuration and tiers.
- `AddSources`: adapted from Coglossa's `DropArea`; the chips belong to the page, not to a
  module queue (R-M18-15).
- `ConfirmDialog`, `Tabs`, `Loading` stay Corelata's (logged in M4b).
- `auth.logout_url` and `SystemInfo.logout_url` copied from Coglossa.

## Spec deviations

- None beyond the M18 spec's §9.1, which records the plan's rulings.

## Rulings during execution

- How the plan applied R-M18-1 to R-M18-5, and the rulings it added (R-M18-6 to R-M18-26), are
  in its Global Constraints. Number new ones from R-M18-27.

## Should fix soon

- The writing page's Stop writing… is still one press, then "Stopping after the current step…"
  (M17's R-M17-17): a run whose worker died needs `corelata cancel` again after
  `worker.stalled_after_s`.

## Later

- Phone-sized layouts (spec §20).
- The sidebar polls `GET /api/projects` every 5 s while any report is being written; a project
  summary in the run channel's notifications would let it follow without polling.
- A shared design package with Coglossa (CRL-3) once both are deployed; the divergences above
  are the list to reconcile.
- `GET /api/runs` loads whole run rows (the report and pack snapshot included) to build
  summaries; deferring the large columns as `get_run_brief` does would make the Reports list
  lighter.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git -C "$REPO" diff --stat main -- docs/m1-followups.md docs/m17-followups.md docs/trace-format.md engine/corelata/render deploy`
Expected: lint clean; the diff lists only `deploy/config/corelata.example.yaml` (Task 3's comment line).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_csp_proxy.py --no-cov -q`
Expected: passed (the guide's nginx sample policy is untouched; the new YAML block is in §6 after it).

- [ ] **Step 6: Commit**

```bash
cat > "$SCRATCH/m18-task10-commit.txt" <<'EOF'
docs: M18 README section, spec amendments, operator guide screens and words, follow-ups (CRL-41)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git -C "$REPO" add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md docs/operator-guide.md docs/m18-followups.md
git -C "$REPO" commit -F "$SCRATCH/m18-task10-commit.txt"
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine    # 964 passed (956 before), coverage >= 95%
make test-api       # 173 passed (171)
make test-web       # 385 passed (211), no "intercepted a request" in the output
make e2e            # 9 passed (6)
make deploy-check
make schema && git -C "$REPO" status --short schema web/src/api/schema.d.ts   # no output
grep -n '^version' engine/pyproject.toml                                        # still 0.1.6
grep -nE '#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(' web/src/styles/*.css | grep -v tokens.css   # no output
```

CI must be green on all six jobs (engine, api, web, e2e, deploy, airgap) and `ci-status` before the merge. The airgap job builds the image with the new `web/dist` and installs the bundle unchanged.

Scratch results this plan was checked on (Tasks 1 to 9 applied to a copy of 3154118): engine 964 passed, 98.46% → 98.47%; api 173 passed, 99.69%; web 385 Vitest in 54 files, 98.96 / 96.86 / 100 / 99.49%; e2e 9 passed; ruff, `pnpm lint` and `pnpm build` clean; `make schema` changed the three files named in Task 3 and was stable on a second run; the build's `dist/` holds `theme-init.js` and the Noto Sans files; screenshots of every screen in both themes looked as Coglossa's family.

## Live rehearsal (the controller runs this after the merge; not a task)

The host has no `psql`: every SQL step runs in the dev database's container,
`docker exec corelata-dev-postgres-1 psql -U corelata -d <database> -c "…"`. Never stop that
container; drop any database the rehearsal creates.

**Screenshots on this host.** Use the Playwright MCP tools (`browser_navigate`,
`browser_resize`, `browser_take_screenshot`, `browser_press_key`, `browser_snapshot`). The theme
is chosen per browser profile: set it on the page with `browser_evaluate`
(`() => { localStorage.setItem("corelata.theme", "dark"); location.reload(); }`), or with the
header's toggle. Save every screenshot to the session scratchpad's `m18-rehearsal/`, named
`<theme>-<nn>-<screen>.png`.

**A. The dev stack in light and dark, every screen.** From the repository root on main after the
merge: `make db-up`, `cd web && pnpm build`, then
`cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run python devstack.py --port 8080 --web-dir ../web/dist`
(a throwaway database, dropped when it stops, the fake model, and the built app on
http://127.0.0.1:8080).

- [ ] At 1440 × 900, for `light` and then `dark`: 01 New report (`/new`, no project); 02 a new
  project's page after dropping `docs/examples/varna-port.txt`, a second text file and a `.png`
  at once (three chips; the `.png` is marked "isn't a file type Corelata reads" and is not sent;
  the dev stack's limit is 200 MB, so the size marking is left to the unit tests); 03 the page with suggestions (**Suggest
  value**); 04 **More options** open; 05 Writing the report while live (the current step marked);
  06 Ready to review; 07 Details open; 08 the Stop dialog (start a second report and press
  **Stop writing…**, then **Keep going**); 09 Review, Claims with a claim selected (the
  highlight in the frame); 10 Standards; 11 Process; 12 Sources; 13 the Download menu open;
  14 Return with note… open; 15 the banner after a return, the revised report being written;
  16 Settings with Technical details open; 17 Help; 18 a not-found page; 19 at 1000 px the review
  with its tabs under the frame; 20 at 850 px the sidebar closed, then open from **Your
  projects**.
- [ ] In dark, the report frame's text is light on the dark surface and the highlight is still
  dark text on yellow; in light, dark on white. Switching the theme on Review changes the report
  without reloading it (the claim stays highlighted).
- [ ] Reload Review in dark with the browser's cache on and off: no white flash before the page,
  none inside the frame.

**B. Coglossa's family.** Open the screenshots beside Coglossa's UI spec
(`$COGLOSSA/docs/superpowers/specs/2026-10-16-coglossa-ui-ux-design.md`, its frame and screen
descriptions and, if a Coglossa dev stack is at hand, the same screens of it in both themes).

- [ ] The colours, type, spacing, buttons (neutral by default, one primary per screen), the
  header, the sidebar (grouping, the row's name and status, the selected row) and the theme
  toggle match; only the product name and the screens' content differ (spec §2.1, 1).

**C. Keyboard only, a full journey.** Unplug the mouse (or do not touch it).

- [ ] From `/new`: Tab to **New project**, create one, Tab to the drop area (its focus ring
  shows on the area), Space opens the file chooser; choose `varna-port.txt`; **Upload**;
  **Suggest value**; Tab to **Use this statement**; open **More options** with Enter; **Write the
  report**. The focus ring is visible on every stop (`:focus-visible`, `--accent`).
- [ ] On Writing the report, wait for **Review the report** and press Enter.
- [ ] On Review: Tab to the tabs and move with ← → Home End; open **Download** with Enter, move
  with ↓ ↑, Esc closes it and focus returns to the button; open **Return with note…**, Esc closes
  the dialog and focus returns; `?` opens Help outside a text field and not inside the note box;
  **Accept** with Enter: the banner says "Accepted on …", both actions are disabled, the sidebar's
  row reads "✓ accepted".

**D. Gates.**

- [ ] `make e2e`: 9 passed.
- [ ] `cd web && pnpm exec vitest run src/styles/contrast.test.ts`: every pair passes in both
  themes, and the highlight pair.
- [ ] `make bundle` on a linux/amd64 builder (or the CRL-1 VM): `deploy/tests/check-bundle.sh`
  prints `ok:`; inside the image, `docker run --rm corelata/app:<version> ls /opt/corelata/web
  /opt/corelata/web/assets | grep -E 'theme-init.js|noto-sans-latin-400'` lists both; installed
  on a sealed host (`make airgap-test`, or the VM without a network), the web app loads its font
  and `theme-init.js` from the bundle (the browser's network panel shows no request leaving the
  host) and the doctor is all PASS.
- [ ] With `auth: { mode: trusted_header, logout_url: /signed-out }` behind the guide's nginx
  example, the header shows the user's name and **Sign out**, whose form posts to `/signed-out`;
  without `logout_url`, no Sign out.
- [ ] Fill in the table, add it to Jira CRL-41 with the screenshots and close it; then cut 0.1.7.

| Measure | M17 (v0.1.6) | M18 |
|---|---|---|
| Vitest | 211 | |
| e2e | 6 | |
| Screens in light and dark, matching Coglossa's family | n/a | |
| Keyboard-only journey to Accept | n/a | |
| Light flash on load (app, frame) | n/a | |
| Contrast pairs passing (both themes) | n/a | |
| Bundle: fonts and `theme-init.js` served offline | n/a | |
