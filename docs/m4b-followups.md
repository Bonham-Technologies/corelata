# M4b follow-ups

## Divergences from Coglossa

- `web/`: package `corelata-web`, title and brand `Corelata`, `NETWORK_ERROR` names Corelata; no
  `@fontsource` packages or `fonts.ts` (Corelata's reports are English; the system font stack
  serves offline); `ApiError` has no `code` (nothing sets one).
- `client.ts` gains `unwrapText` (routes that return a file: the report and the exports) and
  `reportUrl`/`exportUrl` instead of Coglossa's `exportUrl(kind, comments)`.
- `events.ts`: a `progress` event replaces the cached `RunProgress` whole (Coglossa patched a
  `RunDetail`); no refetch on a state change, because the progress carries everything the
  screen shows. `FakeEventSource.fail()` added for the gave-up path (**backport**).
- `useRun(runId, live)`: `live` is computed by the page (EventSource available and not failed)
  and the query polls unless a live stream delivers, instead of Coglossa's `streamFailed`.
- `useReportHtml`/`useReportJson` take an `enabled` flag.
- New primitives: `Tabs` (WAI-ARIA tablist), `ConfirmDialog` (native `<dialog>` with focus
  return; **backport** candidate for Coglossa's `UnsavedChanges`), `ReportFrame`.
- `ConfirmDialog` keeps the native `<dialog>` mounted (so the close effect can restore focus) and
  has `confirmDisabled`.
- `Tabs` ids are `useId()`-prefixed, with `aria-controls` only on the selected tab.
- `ReportFrame` skips `scrollIntoView` for clicks made inside the frame.
- `ProjectPicker` renders its select only after the projects load.
- Test harness: `renderWithClient` beside `renderApp`; `src/test/poll.ts` reads a query's live
  `refetchInterval`; jsdom `<dialog>` shims in `setup.ts`; no `CSS.escape` shim (jsdom has it).
- `devstack.py`: no fake scorer; roles gate/writer/conveyor/auditor; `worker.stalled_after_s: 60`.
- CI `e2e` job identical apart from env names; no font test in `app.spec.ts`.

## Spec deviations

- §10.3: routes and URL state as amended in the spec; the New run screen lists the project's
  runs (not in the spec's screen list); no System screen.
- §10.3 Audit tab: rule titles and the advisory grouping come from the live pack
  (`GET /packs/{name}/resolved`), not the run's snapshot; a renamed or removed pack degrades to
  rule ids.
- §10.3 Sources tab: no per-source hash is shown. `TraceSummary.sources` carries no `sha256` and
  its ids are per-run (`src1`), so they cannot be joined to the project's `SourceView.sha256`; the
  pack hash is shown instead. **Closed in M7:** `SourceSummary.sha256` is shown in a SHA-256 column (BORG-40).
- The source selection is keyed to the project (`{projectId, ids}`) so history navigation never
  carries another project's ids.
- The Start body always sends `extra_guidance: ""` (the generated type requires it).
- `auditRows` keeps findings order for rules not in the pack (the plan's tie-break contradicted
  its own test).

## Should fix soon

- Add `sha256` to `SourceSummary` (engine) and show it in the Sources tab. — **closed in M7**.
- `ReportFrame` writes the report with `document.write` into a same-origin frame; the frame is
  `sandbox="allow-same-origin"` with no scripts, and the renderer autoescapes, but a report that
  ever carried hostile HTML would run in the page's origin. Consider `srcdoc` without
  `allow-same-origin` plus `postMessage` for highlighting — **closed in M7** (`srcdoc`, `sandbox="allow-scripts"`, a `postMessage` bridge; links inside the report are inert; BORG-41).
- The Vitest suite is timing-sensitive under machine load (several tests carry raised timeouts;
  one `NewRunPage` test has 15 s): consider a global `testTimeout` and fewer full-app renders per
  test.
- ~~The effective profile may not be an option of the select (default profile absent from the pack,
  drafts): fall back to `null` when the option is absent.~~ — CRL-108
- `Math.trunc` on audit iterations.
- Key `ValueStatement` by project so stale suggestions clear. — **closed**, verified 2026-10-18: `web/src/pages/new/NewRunPage.tsx` renders it with `key={projectId}`.
- ~~The Audit tab reflows once the pack arrives; show a loading state.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~`dir="auto"` is missing on rule titles and ids and on stage errors.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~No loading state while a selected claim's evidence loads.~~ — **closed in M17** (CRL-40). — CRL-40
- `onStreamFailed` should be held in a ref inside `useRunEvents`.
- ~~`discoveryPollInterval` has no 404 guard; discovery polling (1 s) has no backoff.~~ — **closed in M9** (CRL-8) — CRL-8
- ~~`useCancelRun` does not invalidate the project's run list.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~Run-scoped query keys share the `["runs", id]` prefix: use `exact: true` when invalidating the
  run itself.~~ — **closed in M9** (CRL-15) — CRL-15
- Anchors inside the report navigate the frame: inject `<base target="_blank">` or intercept — **closed in M7** (`srcdoc`, `sandbox="allow-scripts"`, a `postMessage` bridge; links inside the report are inert; BORG-41).
- ~~`json.error` on the review header is silent.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~The review note persists after a successful return.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~The "Accepted" state is local; a reload re-enables Accept.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~The timeline's `sr-only` status text is the raw token.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~`RunList` shows at most 100 runs (the API's limit); no paging.~~ — **closed in M9** (CRL-15) — CRL-15
- ~~The `Suggest value` request sends no `audience_hint`; the form has no field for it yet.~~ — **closed in M17** (CRL-40: an empty hint is left out of the request). — CRL-40
- ~~The client's bare `catch` maps `AbortError` to the network error.~~ — **closed in M17** (CRL-40). — CRL-40
- `location.origin` is read at module load, so `client.ts` cannot be imported outside a DOM.
- Node 26 prints a `localStorage` `ExperimentalWarning` under Vitest (CI uses Node 22).
- `useReportHtml`/`useReportJson` fetch two documents; one `report.json` plus a client-side
  render would save a request but duplicate the renderer.
- ~~The Audit tab fetches the live pack on every review page open (cached 60 s).~~ — **closed in M9** (CRL-8) — CRL-8
- `ProcessTab` labels stage names through `STATE_LABELS` (stage ids equal run states today).
- `ConfirmDialog` relies on the browser's focus restore after `close()`; jsdom needs the
  `showModal`/`close` shims in tests.
- No keyboard shortcut set; tabs and dialogs are keyboard-operable, nothing more.
- No dark mode; `color-scheme` is left to the report frame.

## Later

- M5: delivered (deploy/).
- A System screen over `GET /api/system/doctor` for operators.
- Audience hint for discovery and `extra_guidance` fields on the New run screen; a run detail link
  from the Review screen back to its Progress (the Process tab covers the timeline).
