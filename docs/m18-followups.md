# M18 follow-ups

## Divergences from Coglossa

- `tokens.css`: Coglossa's `--panel-width` and `--guide-width` are dropped (Corelata has no panel
  or guide); two layout tokens are added (`--review-side-width`, `--frame-min-height`); colours
  unchanged.
- `base.css`: a one-family font stack (Noto Sans, then the computer's fonts); the Han `:lang()`
  rules, `mark`, `pre.config`, `.signals` and `.history` dropped (Coglossa-only screens); `.card`
  and the Settings rules (`.settings`, `.appearance`, `.facts`) added.
- `shell.css`: `.project-row`, `.project-link` (current page by `aria-current`), `.project-name`;
  no `.row-menu`; `.sidebar-foot` for the version.
- `theme-init.js`, `theme.ts`: the key `corelata.theme` (Coglossa's is its own).
- `contrast.test.ts`: the frame's highlight pair (`#1a1a1a` on `#fff3b0`) added; **backport
  candidate**: Coglossa has no in-frame colours yet.
- `logical-edges.test.ts` not copied (no flagged-passage bar).
- `test/jsdom-storage.ts` copied, called from Corelata's own `jsdom-env.ts`.
- `fonts.ts`, `fonts.test.ts`: one family.
- `Menu.tsx`: one `eslint-disable-next-line react-hooks/refs`; Corelata keeps the rule on, which
  Coglossa turns off app-wide (R-M18-9). Corelata's `lint` therefore has one suppression Coglossa's
  does not need.
- `Dialog.tsx`, `StatusText.tsx`, `dates.ts`, `keys.ts`: unchanged but a header comment;
  `Dialog.test.tsx` is Corelata's (Coglossa tests it only through others).
- `Layout`: reads `GET /api/system/info` (Corelata has no `/api/me`); provides the active project
  to the sidebar through a context; the version moved from the page footer to the sidebar's foot,
  so M7's "the web footer reports the bundle version" still holds there.
- `Layout`, the sidebar overlay below 900 px (a Corelata improvement, **backport candidate**):
  opening it moves focus to "+ New report", Esc closes it and returns focus to the "Your projects"
  button, and a link click that closes it focuses `<main>` instead of `<body>`. Coglossa's overlay
  has no Esc and no focus handling.
- `shell.css` (M18 polish F5): below 900 px nothing changes; from 900 px the `.workspace` paints
  the sidebar's column (surface, right border) for the full page height, so the column is
  unbroken in a full-page capture and in overscroll. The sidebar itself is Coglossa's sticky,
  one-viewport-tall box, which already followed the scroll live; the strip the rehearsal saw
  (F5, F6) was below it. Coglossa has the same strip; **backport candidate**.
- `base.css` (M18 polish F1): a rule that hides the focus ring on a heading, paragraph or
  section with `tabindex="-1"` (a focus target, not a control; the roving tabs are excluded).
- `Sidebar`: projects, Corelata's statuses (§3.3), no Rename or Delete (Corelata has neither
  route), no ⋯ menu.
- The report frame's theme: the bridge understands one more message, `corelata:theme`
  (`"light"` or `"dark"`, accepted from the parent only), and sets `corelata-theme-light` or
  `corelata-theme-dark` on the frame's root; the rule that applies it is in the nonce-bound
  highlight style, so `report.css`, its hash and the frame's policy are unchanged. Coglossa has
  no in-frame theme.
- `HelpDialog`: Corelata's keys, statuses, steps and standards results.
- `SettingsPage`: no admin split (Corelata has no roles); Status from Corelata's doctor checks, as
  one plain sentence (the check names are under Technical details only); Technical details without
  Coglossa's score search, configuration and tiers.
- `AddSources`: adapted from Coglossa's `DropArea`; the chips belong to the page, not to a
  module queue (R-M18-15).
- `test/engine-words.ts` and its test: the engine-word guard is Corelata's. It fails a screen
  whose visible text, `aria-label`, `placeholder`, `title` or `alt` holds one of the engine's words
  (spec §4, R-M18-14), with the few exact allowances listed in the file. Coglossa has no
  equivalent.
- `ConfirmDialog`, `Tabs`, `Loading` stay Corelata's (logged in M4b).
- `auth.logout_url` and `SystemInfo.logout_url` copied from Coglossa; Corelata's validator is
  stricter (a `/path` that is not `//`, or an `http(s)` URL, with no backslash, whitespace or
  control character), because a browser reads `/\x` as `//x`. **Backport candidate.**

## Spec deviations

- The M18 spec's §9.1 records the plan's rulings, and the deviations R-M18-27 (the minor-issues
  group), R-M18-28 ("waiting for review", "↺ returned") and the sidebar's foot as a `<p>` after
  the `<nav>`.

## Rulings during execution

- How the plan applied R-M18-1 to R-M18-5, and the rulings it added (R-M18-6 to R-M18-26), are
  in its Global Constraints. Number new ones from R-M18-37.
- R-M18-27 and R-M18-28 are the controller's rulings at the whole-branch review; the task rulings
  this file numbered 27 to 34 before then are now R-M18-29 to R-M18-36.
- R-M18-27 (final review): one meaning of "not met", the engine's. The engine counts as open only
  blocking and major failures (`open_findings`, from `stages/audit.py`'s `LOOPING`), and a report
  whose only failures are minor is `clean`. The Standards tab's Not met lists the rules whose
  latest verdict is a blocking or major fail, the set the banner's and the writing page's
  "N standards not met" count; a latest minor fail goes under a new group, **Minor issues**, after
  Not met and before Met and not applicable, with its severity word. The pill stays "✓ Meets the
  standards"; the clean banner adds "N minor issue(s) … listed under Standards." Cost if wrong:
  one group label and a sentence.
- R-M18-28 (final review): "waiting for review" replaces the spec's "to review" (Task 4's
  accessibility fix to the sidebar link's name and status), and "↺ returned" joins the sidebar's
  statuses. Recorded as a spec deviation in §9.1.
- R-M18-29 (Task 3): `ProjectView` stays a separate model from `ProjectSummary` so the counts are
  required in the schema; its field descriptions come from `ProjectSummary`'s.
- R-M18-30 (Task 3): `LatestRun` also carries `child_state`, so the sidebar can tell a returned
  report from one whose revision ended without a report (R-M18-6, R-M18-7).
- R-M18-31 (Task 3): `auth.logout_url` refuses a backslash, whitespace, a control character, and a
  path whose second character is `/` or `\`.
- R-M18-32 (Task 5): the M16 and M17 discovery messages keep the word "Discovery" (owner-agreed
  server copy, spec §2.6); the engine-word guard allows those exact texts and nothing broader.
- R-M18-33 (Task 6): a failed step shows its own recorded error under it, as well as in the
  Outcome alert, because a reader of the steps looks there. Cost if wrong: one line removed.
- R-M18-34 (Task 8): the Settings button "Run a full check" uses "Run" as an English verb, not
  the engine's noun; the guard allows that exact label.
- R-M18-35 (Task 8): the Status sentence is plain words; doctor check names and messages appear
  only under Technical details, so the main flow has no engine word.
- R-M18-36 (Task 9): the end-to-end journeys also assert that the sample Content-Security-Policy
  blocks inline styles and scripts in the report frame in both themes (new coverage).

## M18 polish (before 0.1.7)

Fixes for the live rehearsal's findings, on `m18-polish`:

- **F1 (focus after an action)**: New project moves focus to the new project page's heading;
  Upload to the "N of M selected" status line (once the batch is done, waiting for the list on a
  first upload); Suggest value to a new "Suggestions" heading (only for a discovery started
  here, not one read from the URL on a reload); Accept to the banner. Each target has
  `tabIndex={-1}`; each has a unit test.
- **F3 (Return dialog)**: `ConfirmDialog` takes `initialFocusId`; Return opens in the note field
  (the Stop dialog still opens on its first button).
- **F2 (drop area)**: with no chips the list keeps `--space-3` above the "Add as" row, so the
  ring has room (the gap measured 12 px in both themes).
- **F4 (Appearance)**: a card with an `h2` and a "Theme" radio group, like Status.
- **F5 (sidebar column)**: see the `shell.css` entry under Divergences.

## Should fix soon

- ~~The writing page's Stop writing… is still one press, then "Stopping after the current step…"
  (M17's R-M17-17): a run whose worker died needs `corelata cancel` again after
  `worker.stalled_after_s`.~~ Fixed by CRL-49 (**Stop now…**). — CRL-49

Carried from the task reviews to the final fix wave (it strikes what it fixes):

- ~~`ReviewBanner.tsx` renders an unrecognised degradation line raw without `data-raw-error` (needs
  a guard test with an unknown line)~~ — **fixed in the final wave**.
- ~~`AuditTab.tsx` renders the incomplete notice's reason raw and unmarked~~ — **fixed in the final
  wave**.
- ~~The `coglossa:` allowance in the guard lets engine words follow the slash~~ — **fixed in the
  final wave**.
- Engine words still marked or checked too widely: `RunOutcome.tsx` marks its "No reason was
  recorded." fallback as raw engine text; `StageTimeline.tsx` marks the whole Details line rather
  than only the error; Help's banned-word check is narrower than R-M18-14's list (the guard's
  `expectNoEngineWords` covers Help's screens).
- ~~`ReviewPage.tsx`: the banner's "N not met" comes from `metadata.open_findings`, the Standards
  tab's from each rule's latest verdict; use one~~ — **fixed in the final wave** (R-M18-27: both are
  the latest blocking and major fails).
- ~~The guard's `visiblePrimaryButtons` skips the `<summary>` of a closed `<details>` and has no
  test for it~~ — **fixed in the final wave**.
- ~~Sidebar overlay: its Esc handler should do nothing while a `<dialog>` is open (today one Esc
  closes both)~~ — **fixed in the final wave**.
- ~~Uploads: `FetchFromCoglossa` should be keyed by project with an alive guard, as `AddSources`
  is~~ — **fixed in the final wave**.
- ~~Uploads: the `?discovery=` write in `ValueStatement` and the source toggle and choose handlers
  read the URL at click time, a narrow race with an upload batch in flight.~~ — CRL-62
- ~~A `NewRunPage` test flaked once in a full web run (Task 7); find the cause and fix it~~ —
  **fixed in the final wave** (it asserted the checked state once, before the router's URL update
  had rendered; the same pattern is fixed in `SourcesPanel.test.tsx` and `ProjectPicker.test.tsx`).
- ~~`Menu.tsx`: the reason for the `react-hooks/refs` suppression sits in the comment above the
  directive, not on the directive itself~~ — **fixed in the final wave**.
- ~~`ConfirmDialog` has no test for the non-danger (`primary`) confirm button class~~ — **fixed in
  the final wave**.

Found by the whole-branch review:

- ~~`ConfirmDialog` renders a bare `<dialog>` (unstyled: `base.css` styles `dialog.dialog`) and a
  `secondary` class no stylesheet defines~~ — **fixed in the final wave**.
- ~~Help opens scrolled to the bottom, because focus lands on Close~~ — **fixed in the final wave**
  (focus goes to its heading).
- ~~The report frame can paint in the other theme first on a long report~~ — **fixed in the final
  wave** (the built theme's class is on the frame's `<html>` start tag).
- ~~`new.css` sets `.card { margin-bottom: 0 }` for every page~~ — **fixed in the final wave**
  (scoped to the New report and project pages).
- ~~Help says "the progress page"~~ — **fixed in the final wave** ("the “Writing the report”
  screen").
- ~~`check-app-image.sh` does not check for `theme-init.js` or the fonts~~ — **fixed in the final
  wave**.

## Later

- `GET /api/system/doctor` gives every signed-in user the config path, the storage target and the
  model servers' URLs, which CRL-75 and CRL-86 removed from error bodies. Decision (CRL-112): keep
  them. Corelata has no roles (`SettingsPage` above), so every signed-in user already sees the
  deployment's Settings, and an operator needs them under Technical details to act on a failed
  check. Since CRL-112 the route probes only with `probe=true`, and a probe is shared and reused
  for 30 s, so a caller can no longer make it load the model servers. Revisit if roles land: a
  non-operator would then get the checks' names and statuses without their messages.
- Phone-sized layouts (spec §20).
- ~~The sidebar polls `GET /api/projects` every 5 s while any report is being written; a project
  summary in the run channel's notifications would let it follow without polling.~~ — **CRL-63**:
  a run's open event stream reads the list again when it reports the run's end or its deletion,
  and so does a read of the run (the polling fallback) that sees it end; the list falls back to a
  30 s poll only while more reports are being written than streams are open, so a run no stream
  follows (started earlier, in another tab or by another analyst) still shows its end. Leaving a
  run's page mid-run leaves its row "writing" for up to 30 s after it ends. — CRL-63
- A shared design package with Coglossa (CRL-3) once both are deployed; the divergences above
  are the list to reconcile. — CRL-3
- ~~`GET /api/runs` loads whole run rows (the report and pack snapshot included) to build
  summaries; deferring the large columns as `get_run_brief` does would make the Reports list
  lighter.~~ — CRL-51
- ~~`contrast.test.ts` lists its colour pairs by hand, as Coglossa's does; a new token pair is not
  checked until it is added.~~ — CRL-64
- `make bundle` on the dev Mac: re-pulling `postgres:16-alpine` onto an image store that shares
  its layers makes `docker save` write an incomplete tar, so the SBOM step fails (seen twice, M17
  and M18). CI and the release build use fresh runners, so they are not affected.
