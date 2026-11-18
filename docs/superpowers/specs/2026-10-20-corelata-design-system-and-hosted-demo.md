# Corelata on Coglossa's design system (CRL-41) and a hosted demo (CRL-42) — Design Spec

- **Date:** 2026-10-20
- **Status:** Part A planned (M18 plan, 2026-10-20); Part B for M19
- **Builds on:** `2026-10-12-corelata-v1-design.md` (v1, M1–M17 merged, v0.1.6 published)
- **Reference (read-only):** Coglossa's `2026-10-16-coglossa-ui-ux-design.md` (the target style),
  `2026-10-14-coglossa-hosted-preview-design.md` and `deploy/hosted/` (the hosting template),
  `2026-10-18-user-roles-design.md` (only for how `/me` feeds the header)
- **Becomes:** M18 (Part A, the UI) and M19 (Part B, hosting). M19 starts after M18 merges, because
  the hosted login page and the demo use the new design.
- **Owner's request (2026-10-20):** "Can you review the Coglossa UI for the web app and unify on
  that style/ design? I'm interested in getting Corelata up and ready for a demo session on a
  hosted version just like Coglossa too".

---

## 0. UI review: Corelata and Coglossa as they stand

### 0.1 What was looked at

Corelata `main` at 365afdf (v0.1.6), run with `api/devstack.py` against the fake model, Chromium at
1440 × 900, light mode. A project with `docs/examples/varna-port.txt` went through suggest value,
a run, and review. Screenshots are in the session scratchpad, `m18-shots/`:

| File | Screen |
|---|---|
| `01-new-empty.png` | New run, no project |
| `02-new-with-suggestions.png` | New run with a source and a suggestion |
| `03-run-progress.png`, `04-run-completed.png` | Run progress, live and finished |
| `05`–`09-review-*.png` | Review: Provenance, a selected claim, Audit, Process, Sources |
| `10-return-dialog.png` | The Return with note dialog |
| `11-review-os-dark.png` | Review with the computer in dark mode |

Coglossa was read from source (its tokens, base and shell styles, `theme-init.js`, the frame
components and its tests), not run.

### 0.2 Findings

| Area | Corelata today | Coglossa | Verdict |
|---|---|---|---|
| Colours | Nine custom properties in `app.css`, plus raw `white`, `rgba()` and a fixed `#fff3b0` highlight. No dark set. | `tokens.css`: 16 colour tokens with a light and a dark set, defined on `dialog::backdrop` too. A test forbids raw colours outside it. | **Adopt** `tokens.css` as is. |
| Type | `system-ui` stack. M4b dropped `@fontsource` on purpose ("reports are English"). | 94 bundled Noto families, one per script, from `fonts.ts`. | **Adapt**: one family, Noto Sans (decision 22.1). The brief's "both bundle Noto fonts" is not true of Corelata today. |
| Sizes and spacing | Ad hoc rem values (0.35rem, 0.6rem, 1.05rem) in every rule. | `--space-1…6`, `--radius-1/2`, `--text-xs…xl`, frame widths, all in rem. | **Adopt**. |
| Dark mode | None. Worse, the report frame's stylesheet declares `color-scheme: light dark`, so with the computer in dark mode the report turns dark inside a light app (`11-review-os-dark.png`). | `data-theme` on `<html>`, set before first paint by `theme-init.js`; the toggle and Settings store the choice. | **Adopt**, and make the report follow the app's choice (§0.4). |
| Frame | A top bar with the name and one "New run" link; the signed-in name; a footer with the version. Content centred at 80 rem. | Header (name, theme, Help, Settings, user, Sign out) and a history sidebar; content uses the full width. | **Adapt** (§3): projects instead of sets, no rename or delete. |
| Navigation | Projects are reached only through a `<select>` on New run; a run's way back is "← Project". | The sidebar is always there, grouped Today / This week / Earlier, with a status per row. | **Adopt** the sidebar. |
| Components | `ConfirmDialog` (native `<dialog>`, focus return, busy state), `Tabs` (WAI-ARIA), `StateBadge`, `Loading`, `ErrorMessage`. | `Dialog`, `Menu`, `HelpDialog`, `StatusText` with a `Status {text, symbol, tone}`, `Loading`, `Sidebar`, `dates.ts`. | **Adopt** `Dialog`, `Menu`, `HelpDialog`'s shell, `StatusText`, `dates.ts`. **Keep** Corelata's `ConfirmDialog`, `Tabs` and `Loading` (they do more; logged in M4b). |
| Buttons | Every button is filled accent by default; `secondary` is outlined. Upload and Start look disabled but read as primary. | Neutral by default, `primary` for the one main action, `quiet`, `danger`, `link`. | **Adopt**. Each screen gets exactly one primary button. |
| Wording | The engine's words on screen: "run", "Audit iterations", "Ingesting sources", "Conveyed", "verdict pass", "evidence unit", "Pack icd203-base · cf6fc9be4160", "Cited in: key_judgments[0]". | A word map (its §3.3); no internal word in the main flow. | **Adapt** with Corelata's own map (§4). |
| Review layout | Report frame left, a 5-column Audit table squeezed into the right pane (`07-review-audit.png`): rule titles wrap to six lines. | Side-by-side document, a panel for detail. | **Keep** Corelata's layout (frame plus tabs), **rework** each tab to read as rows, not wide tables. |
| Downloads | Four bare links in the action row. | `Download ▾` menu with plain names. | **Adopt** the menu. |
| Keyboard and focus | Tabs follow the WAI-ARIA keys; dialogs trap focus. Focus rings are the browser default. | `:focus-visible` outline in `--accent` on everything; `?` opens Help; menus close on Esc. | **Adopt**. |
| Status without colour | Badges carry words. The stage timeline shows done / running / failed by a coloured bar only; the word is in `.sr-only`, so a sighted colour-blind reader cannot tell. | Every status is a word or a symbol plus a colour. | **Adopt**: each step gets a symbol. |
| Contrast | Not tested. `--muted` on white is about 5.9:1; disabled controls at 50 % opacity. | `contrast.test.ts` checks every pair the app uses, 4.5:1 for text and 3:1 for meaningful borders, in both themes. | **Adopt** the test and its thresholds. |

### 0.3 What Corelata adopts, adapts and keeps

- **Adopted as is:** `tokens.css`, the theme mechanism (`theme-init.js`, `theme.ts`, the toggle),
  the contrast, no-raw-colours and token tests, the `Dialog`, `Menu`, `StatusText` components, the
  `Status` type and tone classes, `dates.ts`, the header layout and the sidebar's grouping,
  `base.css`'s element styles and button classes, `:focus-visible`, the `?` key for Help.
- **Adapted:** the sidebar (projects, Corelata's statuses, no ⋯ menu), the header (reads
  `/api/system/info`, not `/me`), `base.css`'s font stack, Help's content, Settings (no roles),
  the word map.
- **Corelata's own:** the report frame and its bridge, the review tabs, the run progress steps,
  `ConfirmDialog`, `Tabs`, `Loading`, everything that M9–M17 pinned (§2.6).

### 0.4 The report page and the theme

The report inside the sandboxed frame keeps its own stylesheet, the engine's
`render/templates/report.css`, allowed by its SHA-256 hash in the frame's policy. That file
already declares `color-scheme: light dark` and uses no fixed colours, so it can show either way.
Today it follows the computer, not the app.

**Decision: the report follows the app's theme.** The page tells the frame which theme to use
through the existing bridge (§5.5). `report.css`, its hash, the frame policy and its nonce do not
change. Downloaded HTML still follows the reader's computer, as today. The highlight style
(`#1a1a1a` on `#fff3b0`) reads the same in both themes and stays inside the bridge.

---

## 1. Purpose

Corelata and Coglossa are sold to the same customer and will be demonstrated together. Today they
look like two different vendors. This work brings Corelata onto Coglossa's design system, so the
two read as one family. Then it puts Corelata on the same kind of hosted, password-protected demo
that Coglossa has, so one runbook pattern serves both.

### 1.1 Decisions already made

- **Corelata is a peer to Coglossa** (v1 spec §2.2, §4.3). Reusable modules are copied now, with
  every intentional change logged under "Divergences from Coglossa" in `docs/m18-followups.md` and
  `docs/m19-followups.md`. A shared package is extracted only after both products are deployed
  (CRL-3).
- **The hosting template is Coglossa's:** Vercel front door, Modal compute that scales to zero,
  Supabase Postgres and Storage, OpenRouter models.
- **The air-gapped v1 deployment is unchanged.** Everything new is additive and off by default.
  The compose stack, the bundle, `install.sh`, the air-gap CI job and the release workflow behave
  exactly as before.
- **No new runtime JavaScript packages.** The customer vets every package. Controls are built-in
  elements: `<dialog>`, `<details>`, `<select>`, and Coglossa's small `Menu` component. (Coglossa's
  spec named the `popover` attribute; its plan replaced it with `Menu`, a state-driven
  `role="menu"`. Corelata copies the component, so both products behave the same.)
- **Desktop first, rem sizes, keyboard access with `:focus-visible`.** Phones are not a target.
- **The ICD 203 + ICD 206 base pack stays the default** on both deployments.
- **Corelata has no user roles.** Every signed-in person sees every project, on the air-gapped
  install and on the demo.

---

# Part A — Corelata on Coglossa's design system (CRL-41, M18)

## 2. Design system

### 2.1 Success criteria (M18)

1. Side by side, Corelata and Coglossa share colours, type, spacing, buttons, the header, the
   sidebar and the theme toggle. Only the product name and the screens' content differ.
2. Dark mode covers every screen, the report page included. It follows the computer until the
   person picks a theme, and loads without a light flash.
3. Text meets WCAG AA in both themes, checked by the copied contrast test with Coglossa's
   thresholds. No stylesheet but `tokens.css` holds a raw colour.
4. No engine word appears in the main flow (§4.4 lists where the expert words remain).
5. Every current capability is within one click of where it is used (§5.7).
6. The behaviours M9–M17 pinned are unchanged (§2.6).
7. CI stays green: `engine`, `api`, `web` (Vitest at 95 %), `e2e`, `deploy`, `airgap`, `ci-status`.

### 2.2 Files copied from Coglossa

| Coglossa file | Corelata file | Change |
|---|---|---|
| `web/src/styles/tokens.css` | same | Header comment names this spec. Adds `--review-side-width: 30rem` and `--frame-min-height: 30rem`. Colour values unchanged. |
| `web/src/styles/base.css` | same | Font stack is `"Noto Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (§2.4). The `:lang()` Han rules, `.signals`, `.history`, `pre.config` and `mark` are dropped (Coglossa-only screens). |
| `web/src/styles/shell.css` | same | `.set-row`/`.set-link`/`.set-name` become `.project-row`/`.project-link`/`.project-name`; `.row-menu` dropped; `.sidebar-foot` added for the version. |
| `web/public/theme-init.js` | same | Storage key `corelata.theme`. |
| `web/src/theme/theme.ts` and its tests | same | `THEME_KEY = "corelata.theme"`. |
| `web/src/styles/contrast.test.ts` | same | Same thresholds (4.5:1 text, 3:1 meaningful borders) and the same pairs; one row per new pair §5 uses. Plus one case: the bridge's highlight pair (`HIGHLIGHT_CSS`, `#1a1a1a` on `#fff3b0`) reaches 4.5:1. |
| `web/src/styles/no-raw-colours.test.ts` | same | Unchanged. It scans `src/styles/*.css`; the frame bridge's colours are TypeScript inside the frame and covered by the highlight case above. |
| `web/src/styles/tokens.test.ts` | same | Unchanged. |
| `web/src/styles/logical-edges.test.ts` | — | Not copied: Corelata has no flagged-passage bar. |
| `components/Dialog.tsx`, `Menu.tsx`, `StatusText.tsx` and tests | same | Unchanged. |
| `components/HelpDialog.tsx` | same | Corelata's content (§5.6). |
| `components/Layout.tsx`, `Sidebar.tsx` | same | Adapted (§3). |
| `lib/dates.ts` and tests | same | Unchanged. |
| `lib/keys.ts` (`keyBelongsToControl`) | same | Unchanged; used by the `?` shortcut. |
| `settings/SettingsPage.tsx` (Appearance) | same | Appearance unchanged; Status and Technical details are Corelata's (§5.6). |

`index.html` loads `/theme-init.js` with a plain blocking `<script src>` in `<head>`, as in
Coglossa. It is a file, not inline, so the operator guide's sample site policy
(`script-src 'self' 'unsafe-inline'`) and any stricter one allow it.

### 2.3 Corelata's own stylesheets

`app.css` is deleted. Its rules move, rewritten on the tokens, into `base.css`, `shell.css` and
three screen sheets: `new.css` (New report and the project page), `run.css` (progress) and
`review.css` (review). No sheet but `tokens.css` holds a hex, `rgb()` or `hsl()` value; the copied
test enforces it. `.sr-only` becomes Coglossa's `.visually-hidden`.

### 2.4 Type

Corelata bundles **Noto Sans** 400 and 700 from `@fontsource/noto-sans@5.3.0`, the exact package
and version Coglossa ships, imported in `src/fonts.ts`. The customer has already vetted it for
Coglossa. Other scripts fall back to the system fonts, as today. This reverses the M4b choice
and needs the owner's yes (decision 22.1); without it, the stack starts at `system-ui` and
everything else in this spec stands.

### 2.5 Divergence-log entries (M18)

Recorded in `docs/m18-followups.md` under "Divergences from Coglossa":

- `tokens.css`: two layout tokens added (`--review-side-width`, `--frame-min-height`); colours
  unchanged.
- `base.css`: one-family font stack; Han `:lang()` rules and Coglossa-only classes dropped.
- `shell.css`: project row classes; no row menu; a sidebar footer with the version.
- `theme-init.js`, `theme.ts`: key `corelata.theme`.
- `contrast.test.ts`: the frame highlight pair added (**backport** candidate: Coglossa has no
  in-frame colours yet).
- `logical-edges.test.ts` not copied.
- `Layout`: reads `GET /api/system/info` (Corelata has no `/api/me`); the version moves from the
  page footer to the sidebar's foot, so M7's "the web footer reports the bundle version" still
  holds.
- `Sidebar`: projects, Corelata's status rules (§3.3), no Rename or Delete (Corelata has neither
  route), no ⋯ menu.
- `HelpDialog`: Corelata's shortcuts and statuses.
- `SettingsPage`: no admin split (Corelata has no roles); Status uses Corelata's doctor checks.
- `ConfirmDialog`, `Tabs`, `Loading` stay Corelata's (already logged in M4b).
- `auth.logout_url` and `SystemInfo.logout_url` copied from Coglossa (§7.3).

### 2.6 Behaviour that does not change

Plans and reviews hold M18 to these. Tests that pin them keep their assertions; only selectors and
visible words may change.

- **Polling and ceilings:** `POLL_MS` 3 s for a run without a live stream or with a pending rerun;
  the SSE fallback; discovery polling 1, 2, 4 s then 5 s, and its ceiling
  `max(10 minutes, deadline_at − created_at + 15 s)` on the server's clock, with the same
  live-region texts (reworded only as §4.3 allows, and the fallback sentence word for word).
- **URL state:** `/new?project=<id>&sources=<id>,…&discovery=<id>` (since CRL-54 the page writes
  `pick=` in place of `sources=`, which it still reads) with replace navigation, the
  rules for missing and foreign source ids, a project change dropping both;
  `/runs/<id>/review?tab=&claim=` with the tab ids `provenance`, `audit`, `process`, `sources`.
- **Accept and return:** the button rules from `ReviewActions` (disabled while busy or decided,
  re-enabled when the rerun ended without a report, the note offered again, 409 re-reads the run),
  the M16 "accept is final" behaviour, refetch on focus.
- **The frame:** `sandbox="allow-scripts"`, `srcdoc`, the frame CSP with the report stylesheet's
  hash and the per-render nonce, inert links, the 200-character claim cap, `scroll` only for
  selections made outside the frame. The bridge gains one message (§5.5); nothing else in it
  changes.
- **Routes:** `/` redirects to `/new`; `/new`, `/runs/:runId`, `/runs/:runId/review` stay. One
  route is added: `/settings`.

## 3. The frame

### 3.1 Header

- **Left:** a "Your projects" button below 900 px (opens the sidebar), then the **Corelata** name,
  which links to `/new`.
- **Right:**
  - the theme toggle (☾ / ☀), with an `aria-label` naming the theme it switches to;
  - **Help**, which opens the help dialog (§5.6);
  - **Settings**, a link to `/settings`;
  - the signed-in name, from `GET /api/system/info`'s `user`, shown only when it is not null;
  - **Sign out**, a POST form to `logout_url`, shown only when `/api/system/info` reports one.

`GET /api/system/info` reports today: `version`, `auth_mode`, `user`, `coglossa` (whether the
fetch is configured), `max_upload_mb`, `default_pack`, `default_profile`. M18 adds `logout_url`
(§7.3). It is read once (`staleTime: Infinity`), as today.

### 3.2 What the sidebar lists: projects

**Decision: the sidebar lists the user's projects, newest activity first. A project's reports are
listed on its page, not in the sidebar.**

Why, against Corelata's routes and APIs:

- A project is what the analyst names and comes back to: one tasking line, its sources, and the
  reports written from them. A return makes a revised report inside the same project.
- `GET /api/projects` already lists every project in one call. Runs have no cross-project listing:
  `GET /api/runs` needs `project_id` and pages by cursor (CRL-24), because one project can hold
  hundreds of runs. Listing recent reports would need a new cross-project endpoint, and nesting
  runs under each project would need a request per project.
- The project page, `/new?project=<id>`, already holds the project's sources, the new-report form
  and its runs. With the sidebar, every report is two clicks from anywhere: the project row, then
  the report.

### 3.3 The sidebar

- **+ New report**, a primary button that links to `/new`.
- **Search** filters by name once there are more than 15 projects (Coglossa's `SEARCH_FROM`).
- **Groups:** Today, This week and Earlier, by `last_activity_at` (`dates.ts`, unchanged).
- **Each row** is a link to `/new?project=<id>` with the project's name (`dir="auto"`) and one
  status, chosen in this order:

  | Condition (from §7.1's fields) | Status |
  |---|---|
  | `reports_writing > 0` | `…` writing (busy) |
  | `reports_to_review > 0` | `●` N to review (busy) |
  | latest run `failed` | `!` needs attention (bad) |
  | latest run `gate_rejected` | `⚠` not supported (warn) |
  | latest run `completed`, decision `accepted` | `✓` accepted (ok) |
  | latest run `cancelled` | `■` stopped (none) |
  | no runs | no reports yet (none) |
  | anything else | the latest run's word from §4.3 |

- **The active row** is the project of the page on screen: the project page, or the project of the
  run shown. It gets `--selected` and `aria-current="page"`.
- **Freshness:** the list is refetched when the window regains focus; after any mutation that
  creates a project, a source or a run, or records a review; when a run's progress stream reports
  a terminal state; and every 5 s while any row is writing. Nothing else polls it.
- **Foot:** "Corelata 0.1.6" (the API's `version`) in muted text, as a `<p>` at the sidebar's
  foot, after the `<nav>` and outside it (§9.1).
- **Below 900 px** the sidebar is an overlay opened from the header, as in Coglossa.

### 3.4 Browser tab titles

| Screen | Title |
|---|---|
| New report, no project | New report – Corelata |
| Project page | <project name> – Corelata |
| A report being written | Writing… – <project name> |
| A report ready to review | ✓ Ready to review – <report title> |
| Review | <report title> – Corelata |
| Settings | Settings – Corelata |

## 4. Wording

Corelata's users are analysts and reviewers. They understand "report", "sources", "claims",
"value statement", "evidence" and "standards". The engine's own words stay in the API, the CLI,
the trace and the Process tab.

### 4.1 Engine words on screen

| Engine word | On screen |
|---|---|
| project | **project**. It is a plain word for a tasking line's folder, and the CLI and API use it. |
| run | **report**: "Write the report", "Writing the report", "Reports" on the project page. "Run" is not shown. |
| rerun, child run | **revised report** |
| discovery | **suggestions**: the button stays **Suggest value** |
| source unit, evidence unit | **passage**: "1 passage", "Evidence for claim c0" |
| locator | kept as is (`para 1`, `page:3/para:7`), after the source name |
| gate | **value check**; its stage is "Checking the value statement" |
| `gate_rejected` | **not supported by the sources** |
| writer | **writer** ("Note for the writer" stays) |
| conveyor, conveying | **editing for the reader** |
| auditor, audit | **standards check**; the tab is **Standards** |
| finding, verdict `fail` | **not met** (symbol ✗) |
| verdict `pass` | **met** (✓) |
| verdict `not_applicable` | **doesn't apply** (–) |
| verdict `attested` | **attested** (◇), in the "Advisory" group |
| severity `blocking` / `major` / `minor` | Blocking / Major / Minor (the pack's words, capitalised) |
| status `clean` | **Meets the standards** |
| status `findings_open` | **N standards not met**, or **Checked in part** when the only reason is a degradation |
| degraded (`metadata.degradations`) | **delivered without a full check**: "Editing for the reader was skipped after N attempts." / "The standards check didn't finish after N attempts." The engine's error goes under Details. A line in neither form is shown as it is. |
| iteration, `max_iterations` | **revision**, **revision rounds** ("Revision 1 of 2"; the option "Revision rounds") |
| profile | **team profile** |
| pack | **standards pack**, only in the Sources tab and Settings |
| digest, digested | **summarised** ("summarised before drafting") |
| claim kinds `fact` / `judgment` / `assumption` | Fact / Judgment / Assumption |
| `cited_by` paths (`key_judgments[0]`, `analysis[0].paragraphs[1]`) | "Key judgments, item 1", "Analysis, section 1, paragraph 2"; an unknown path is shown as it is |
| trace | **trace**, only in the Download menu ("Trace (JSON)") and the Process tab |
| model calls, tokens | Process tab and the progress page's Details fold only |

### 4.2 Report states (a run's `state`, plus its review decision)

One function, `runStatus(run)`, gives each run a `Status` (Coglossa's type). The sidebar, the
project page's list and the progress page use it.

| State | Status |
|---|---|
| `created` | `…` waiting to start (busy) |
| `ingesting` … `rendering` | `…` writing (busy) |
| `completed`, no decision, or a return whose revision ended without a report | `●` to review (busy) |
| `completed`, accepted | `✓` accepted (ok) |
| `completed`, returned, revision live or completed | `↺` returned (none) |
| `gate_rejected` | `⚠` not supported by the sources (warn) |
| `failed` | `!` couldn't finish (bad) |
| `cancelled` | `■` stopped (none) |

### 4.3 Progress steps

| State | Step |
|---|---|
| `created` | Waiting to start |
| `ingesting` | Reading the sources |
| `gating` | Checking the value statement |
| `drafting` | Drafting |
| `conveying` | Editing for the reader |
| `auditing` | Checking against the standards |
| `rendering` | Preparing the documents |
| `completed` | Ready to review |

On a revision (`iteration > 0`) the drafting, editing and checking steps carry "revision N of M".
The discovery live-region texts become "Waiting for Corelata to start looking…" (`created`) and
"Looking for value in the selected sources…" (`running`, unchanged). The 10-minute fallback
sentence is unchanged, word for word.

### 4.4 Where the expert words stay

The Process tab (stage names with the engine word in brackets, roles, iterations, tokens), the
Sources tab (SHA-256, unit counts, the pack name and hash), Settings ▸ Technical details, and the
downloads. The API, CLI, trace and exports are unchanged.

## 5. The screens

All screens sit in the frame (§3). Each has one primary button.

### 5.1 New report, no project (`/new`)

- Heading **New report**.
- A card, **Which project is it for?**
  - a `<select>` of existing projects ("Choose a project…"), as today's `ProjectPicker`;
  - **New project**, which reveals a name field with **Create** (primary) and **Cancel**, as today.
- Choosing or creating a project replaces the URL with `/new?project=<id>`, as today.

### 5.2 The project page (`/new?project=<id>`)

- An eyebrow "Project" and the project's name as the heading. No picker: the sidebar switches
  projects and **+ New report** goes back to §5.1.
- **Sources** card:
  - one row per source: a checkbox ("Use <name> in this report"), the name, and its kind in words
    ("TXT", "Coglossa run 1234…"); "N of M selected" in a polite live region, as today;
  - **Add sources**: a drop area that takes one or more files by drag and drop or by browsing, with
    the same accepted types as today (`.docx .pdf .txt .md .html .htm .json .csv`);
    - an "Add as" `<select>`: **Documents** (default) or **Coglossa exports**, for the files dropped;
    - each file becomes a chip with its name, its size and a remove button;
    - a file over `max_upload_mb` is marked at once: "notes.pdf is 6 MB, and the limit is 4 MB";
    - **Upload** sends the files one after another (one request each, as the API takes them); a
      failed file's chip says why (413: "too large for this server"; otherwise the API's one line)
      with **Try again**; the others carry on;
  - **Fetch from Coglossa**, when `coglossa` is true, unchanged in behaviour.
- **Value statement** card: the text area, **Suggest value**, and the suggestions as cards with
  "For <audience> · N passages", the confidence note, and **Use this statement**. The discovery
  behaviour is §2.6's.
- **More options**, a `<details>` fold, closed: **Team profile** (the select, as today) and
  **Revision rounds** (0–10, default 2, as today).
- **Write the report** (primary), with "Choose at least one source." beside it when none is
  chosen.
- **Reports** card: today's `RunList` as rows: when ("3 hours ago", full date in `title`), the
  value statement, the status (§4.2), and **Review**, **Progress** or **Outcome**. **Show more**
  pages by cursor, unchanged.

### 5.3 Writing the report (`/runs/<id>`)

- A breadcrumb to the project, then the heading: **Writing the report** while live, otherwise the
  outcome's heading.
- **Steps** (§4.3) as an ordered list. Each step has a symbol and a word, never colour alone:
  ✓ done, ● now (with "revision N of M"), ! failed, ○ not yet. The current step has
  `aria-current="step"`.
- The line "This usually takes a few minutes. You can leave this page; it keeps going."
- "Live updates are off; checking every few seconds." when the stream is unavailable, as today.
- **Details**, a `<details>` fold, closed: each stage's duration, attempts and error (today's
  timeline text), the attempt count after a requeue, and the token usage line.
- **Stop writing…** (secondary, danger) opens the confirm dialog "Stop this report?" with "It stops
  after the step in progress; no report will be produced." and **Stop** / **Keep going**. After
  the request: "Stopping after the current step…", as today.
- **Outcomes:**

  | State | Heading and body | Next |
  |---|---|---|
  | `completed` | **Ready to review.** "Meets the standards." or "N standards not met; they're listed under Standards." Notes for a cancel that came too late and an export error, as today. | **Review the report** (primary) |
  | `gate_rejected` | **Not supported by the sources.** "The value check didn't find this in the sources." The reasons, and the suggested scope. | **Try another statement** (the project page) |
  | `failed` | **This report couldn't be written.** The error, in plain text. | **Start a new report** |
  | `cancelled` | **Stopped before the report was written.** | **Start a new report** |

### 5.4 Review (`/runs/<id>/review`)

- **Header row:** a breadcrumb to the project; the report's title (`dir="auto"`); the status pill
  (§4.1); then **Accept** (primary), **Return with note…**, and **Download ▾**, a `Menu` with
  "Word document (DOCX)", "Markdown", "Web page (HTML)" and "Trace (JSON)" (today's four URLs).
- **Summary banner,** one sentence:

  | Condition | Banner | Action |
  |---|---|---|
  | no decision, `clean` | Ready to review. Every standard the pack can check was met. | none |
  | no decision, open findings | Ready to review. N standards not met. | **Show them** (opens the Standards tab) |
  | degradations | Delivered without a full check. <the §4.1 line> | **Details** (the engine's line) |
  | accepted | Accepted by <actor> on <date>. | none |
  | returned, revision live | Returned with a note. The revised report is being written. | **Open the revised report** |
  | returned, revision completed | Returned with a note. | **Open the revised report** |
  | returned, revision ended without a report | today's rerun-outcome sentence (M15) | Accept and Return enabled again |

- **Body:** two columns. The report frame on the left (the rest of the width, at least
  `--frame-min-height` tall, filling the window below the header). The tabs on the right,
  `--review-side-width` wide. Below 1100 px the tabs move under the frame.
- **Claims** (tab id `provenance`): the claims as rows, "c0", the claim text, "Judgment · likely ·
  1 passage"; the selected one on `--selected`. Under the list, "Evidence for claim c0": each
  passage with "<source> · <locator>" and the text as a quote; "Cited in: Key judgments, item 1".
  "Loading evidence…" while it loads, as today.
- **Standards** (tab id `audit`): one block per rule, not a table. The rule's title (`dir="auto"`)
  with its id in muted text; the latest verdict as symbol and word; the severity; a **Why**
  `<details>` with the auditor's evidence and recommendation; the history, e.g. "✗ not met → ✓ met".
  Groups: **Not met** first, then **Met and not applicable**, then **Advisory** (attested). The
  incomplete-audit notice and the "rule titles are unavailable" fallback stay, reworded.
- **Process** (tab id `process`): today's content (stage table, drafts, usage by role) with §4.4
  wording and tokens' styles.
- **Sources** (tab id `sources`): today's table with "Standards pack icd203-base (cf6fc9be4160),
  team profile <name>" above it; "summarised before drafting" for a digested source.
- **Return with note…** opens today's dialog with the new styles: "Return the report to the
  writer", the note box, "The note becomes guidance for the revised report.", **Return** /
  **Cancel**.

### 5.5 The report frame and the theme

- The bridge gains one host-to-frame message: `{type: "corelata:theme", theme: "light" | "dark"}`.
- The bridge's nonce-bound style gains two rules: `:root.corelata-theme-light { color-scheme: light }`
  and `:root.corelata-theme-dark { color-scheme: dark }`. On the message, the bridge sets the
  matching class on the frame's `<html>` and removes the other.
- `ReportFrame` posts the resolved theme (`useTheme().theme`) when the bridge reports ready and
  whenever the theme changes.
- `.report-frame` has `background: var(--surface)` and a `--border` border, so the frame shows
  the app's surface behind the report in both themes.
- Unchanged: `report.css` and its hash, `FRAME_CSP`, the nonce, the highlight colours, every
  other message and check.

### 5.6 Settings (`/settings`) and Help

**Settings**, for everyone (Corelata has no roles):

- **Appearance:** Theme, with Match my computer (default), Light and Dark (copied).
- **Status:** one sentence from `GET /api/system/doctor?probe=false`, loaded when the page opens.
  The first failing check decides it:

  | Failing check | Sentence |
  |---|---|
  | none, no warnings | ✓ Everything is working. |
  | none, some warnings | ✓ Everything is working. N notes are under Technical details. |
  | `database` | Corelata can't reach its database. Reports can't start until an administrator fixes it. |
  | `backends` or a `model …` check | Corelata can't reach a model server (<check name>). Reports can't be written until an administrator fixes it. |
  | `storage` | Corelata can't store files. Uploads and reports fail until an administrator fixes it. |
  | `config` | The configuration has a problem: <message>. |
  | any other | Something needs an administrator's attention: <check name>. |

  **Run a full check** calls the doctor with `probe=true` (test completions) and announces its
  sentence in a `role="status"` region, as Coglossa does.
- **Technical details ▸**, a `<details>` fold: the version, the sign-in mode, the upload limit, the
  default pack and team profile, the packs and their profiles (`GET /api/packs`, drafts marked),
  and the doctor's lines as a table (status, name, message, fix).

**Help** (a `Dialog`, opened by the header button or `?` outside a text field):

- Keyboard: `?` opens Help; `←` `→` `Home` `End` move between tabs; `Esc` closes a menu or a dialog.
- What the statuses mean (§4.2), with their symbols.
- The steps (§4.3) in one line each.
- Met, not met, doesn't apply, attested; what Return with note does.

### 5.7 Every capability, within one click

| Capability | Where |
|---|---|
| Switch project | Sidebar |
| Create a project | + New report ▸ New project |
| Upload sources, as documents or Coglossa exports | Project page ▸ Sources |
| Fetch from Coglossa | Project page ▸ Sources (when configured) |
| Choose sources | Project page ▸ Sources |
| Suggest value, use a suggestion | Project page ▸ Value statement |
| Team profile, revision rounds | Project page ▸ More options |
| Earlier reports of a project, paged | Project page ▸ Reports |
| Stage durations, attempts, errors, tokens | Writing page ▸ Details |
| Stop | Writing page |
| Gate reasons and suggested scope | Writing page outcome |
| Accept, Return with note | Review header |
| Downloads (DOCX, Markdown, HTML, trace) | Review ▸ Download ▾ |
| Claims and their evidence | Review ▸ Claims |
| Rule-by-rule results and history | Review ▸ Standards |
| Stages, draft changes, usage by role | Review ▸ Process |
| Source hashes, pack and profile | Review ▸ Sources |
| Installation checks | Settings ▸ Status, Technical details |
| Theme | Header toggle; Settings ▸ Appearance |
| Version | Sidebar foot; Settings ▸ Technical details |

## 6. Controls, layout and accessibility

- **Built-in elements only:** `<dialog>` through `Dialog` and `ConfirmDialog`, `<details>` for
  folds, `<select>` for choices, Coglossa's `Menu` for Download.
- **Sizes** in rem; widths from tokens. Designed for 1280 px and wider with no maximum width;
  below 1100 px the review tabs stack; below 900 px the sidebar overlays. Nothing else is tuned
  for narrow screens.
- **Keyboard:** every control is reachable and shows a `:focus-visible` outline in `--accent`.
  Dialogs trap focus and return it (unchanged). The Menu follows Coglossa's arrow, Home, End and
  Esc keys.
- **Status** is always a word or a symbol plus a colour (§4.2, §5.3, §5.4).
- **Live regions:** the selected-sources count, the discovery messages and Settings' full check
  stay polite; errors stay `role="alert"`.
- **Text direction:** `dir="auto"` stays on every user-supplied or model-written string.

## 7. Backend changes for M18

All additive. No migration. The CLI and other API clients are unaffected; the bundle smoke test
(`deploy/tests/smoke.py`) reads `GET /api/projects` and ignores new fields.

### 7.1 A summary on `ProjectView`

`GET /api/projects`, `GET /api/projects/{id}` and `POST /api/projects` gain:

| Field | Type | Meaning |
|---|---|---|
| `last_activity_at` | datetime | The latest of the project's `created_at`, its sources' `created_at`, and its runs' `created_at` and `finished_at`. The sidebar sorts and groups by it. |
| `reports_writing` | int | Runs not in a terminal state |
| `reports_to_review` | int | Runs `completed` whose `review_state` is null, or is a return whose `child_state` is `failed`, `cancelled` or `gate_rejected` (the M15 rule) |
| `latest_run` | `LatestRun \| null` | The newest run by `(created_at, id)`: `{run_id, state, status, decision}`, `decision` from `review_state` (`accepted`, `returned` or null) |

They are computed in `store/runs.py` with three queries for the whole list, whatever its length:
one aggregate over `run` grouped by `project_id` (with `FILTER` clauses), one `DISTINCT ON
(project_id)` ordered by `created_at DESC, id DESC` (served by `ix_run_project_created`), and one
`max(created_at)` over `source` grouped by `project_id`. `get_project` runs the same three with a
`WHERE`. No query per project.

### 7.2 `RunSummary.review_decision`

`GET /api/runs` rows gain `review_decision: accepted | returned | null`, from the same
`review_state` the run's `GET /runs/{id}` reads, so the Reports list shows "accepted" and
"returned" without a request per row.

### 7.3 `auth.logout_url` and `SystemInfo.logout_url`

Copied from Coglossa: `auth.logout_url: str | None = None` in `AuthConfig` (operational, outside
`config_hash`), and `logout_url` in `SystemInfo`. The air-gapped install leaves it unset, so no
Sign out appears; a site whose proxy has a sign-out page may set it (operator guide, section 6).

### 7.4 Regeneration and route checks

`make schema` regenerates `schema/openapi.json` and `web/src/api/schema.d.ts`.
`api/tests/test_openapi.py::test_every_screen_has_its_routes` gains the Settings screen
(`/api/system/info`, `/api/system/doctor`, `/api/packs`). No new route.

## 8. Testing (M18)

### 8.1 Component tests (Vitest, 95 % gate)

| Unit | Tests |
|---|---|
| Theme | stored choice, the system default, live system changes, `localStorage` throwing (copied) |
| `theme-init.js` | sets `data-theme` from the stored choice and the system (copied) |
| Contrast, raw colours, tokens | copied, plus the highlight pair |
| Layout | the name, toggle, Help, Settings; the user and Sign out only when `/api/system/info` reports them; `?` opens Help outside text fields only |
| Sidebar | grouping by date; each status in §3.3; search from 16 projects; the active row for a project page and for a run's page; refetch while writing |
| `runStatus`, `projectStatus` | every row of §3.3 and §4.2 |
| Wording helpers | `cited_by` paths, degradation lines (both forms and an unknown one), verdict and kind words |
| Project page | drop area: several files, the type filter, over-limit marking, uploads in order, one failing while the next continues, 413 text; More options; Write the report |
| Writing page | every step and symbol; revision labels; Details content; Stop dialog; every outcome |
| Review | every banner row; Download menu URLs; the Standards groups and history; Claims wording |
| `ReportFrame` and the bridge | the theme message sets the class, on ready and on change; nothing else in the bridge changes (existing tests unchanged) |
| Settings | every status sentence; the full check's announcement; Technical details |
| Pinned behaviour (§2.6) | the existing tests for polling, ceilings, URL state, review rules and the frame keep their assertions; only selectors and words change |

### 8.2 Backend tests (pytest, 95 % gate)

The §7.1 fields across mixed states: several runs per project (only the newest is `latest_run`),
a return whose revision failed (counts to review), an accepted report, an empty project, a
project with sources and no runs. A query count shows three statements for 1 and for 20 projects.
`review_decision` for each decision. `logout_url` in `SystemInfo` set and unset.

### 8.3 End to end (Playwright)

- `journey.spec.ts` is rewritten for the new words: + New report, a new project, upload
  `port.txt`, Suggest value, reload (the discovery stays), use a suggestion, Write the report, the
  steps reach "Ready to review", review, select a claim (highlight in the frame), the Standards and
  Process and Sources tabs, the Download menu's four URLs, Return with note, the revised report
  completes. Every request stays on the app's origin.
- The reload test keeps the project, tab and claim.
- `app.spec.ts`: the not-found page; "Corelata <version>" in the sidebar's foot (a `<p>` after
  the `<nav>`, not a `contentinfo` landmark, so the test finds it by its text).
- **Dark mode:** with the theme set to dark, `data-theme="dark"` is on `<html>` before the first
  paint, the main screens render, and the report frame's body text is light on a dark background.
- `csp.spec.ts` (behind the sample policy) unchanged in what it checks, and it passes in both
  themes.

## 9. Rollout (M18)

One branch and one PR, merged when every CI check passes. The bundle picks up the new `web/dist`
with no other change. `docs/operator-guide.md` section 7 (the web screens) is updated to the new
words and screens; the v1 spec §10.3 gets an M18 amendment that points here and records the one
reworded M17 live-region text (§4.3).

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
- §5.6: `backend <name>` failures read as a model server's too (R-M18-8). The status sentence is
  plain words; the doctor's check names and messages appear only under Technical details
  (R-M18-14).
- §7.1: the newest run is a `DISTINCT ON` statement written out in SQL (R-M18-17).
- §7.3: `LatestRun` also carries `child_state`, and `auth.logout_url` is refused unless it is a
  `/path` or an `http(s)` URL with no backslash, whitespace or control character.
- §7.4: the route test already lists Settings' routes; no edit (R-M18-22).
- §2.2: `Menu.tsx` carries one lint suppression (Corelata keeps `react-hooks/refs` on), and
  Coglossa's `test/jsdom-storage.ts` is copied too, for Node 25 and later (R-M18-9, R-M18-16).
  `tokens.css` drops `--panel-width` and `--guide-width` and adds `--review-side-width` and
  `--frame-min-height`.
- The words the tables do not give are R-M18-13's.

Deviations made during execution and at the whole-branch review, each with its ruling:

- §3.3 and §4.2 (R-M18-28): "waiting for review" replaces "to review" (Task 4's accessibility
  fix to the sidebar link's name and status): the sidebar row reads "● 2 waiting for review", a
  report's status "● waiting for review". "↺ returned" joins the sidebar's statuses: a project
  whose latest report was returned, with its revision being written or written, shows it, from
  §4.2's row for that state.
- §5.4 (R-M18-27): one meaning of "not met", the engine's. The engine counts as open only
  blocking and major failures (`open_findings`, from `stages/audit.py`'s `LOOPING`), and a report
  whose only failures are minor is `clean`. So the Standards tab's **Not met** lists the rules
  whose latest verdict is a fail at blocking or major severity, the same set as the banner's and
  the writing page's "N standards not met". A latest fail at minor severity goes in a group of its
  own, **Minor issues**, after Not met and before Met and not applicable, each rule with its
  severity word. The pill stays "✓ Meets the standards", and the clean banner adds the count:
  "Ready to review. Every blocking and major standard that could be checked was met. 1 minor
  issue is listed under Standards." (or "N minor issues are listed…").
- §3.3 and §8.3: the sidebar's foot is a `<p>` after the `<nav>`, outside it, rather than a
  `<footer>` inside it, so the navigation landmark holds only the projects; the e2e test finds the
  version by its text.

---

# Part B — A hosted demo on Coglossa's template (CRL-42, M19)

## 10. Purpose and success criteria

A public, password-protected Corelata that the owner can demonstrate in a browser, built exactly
like Coglossa's preview so one runbook serves both.

1. A person with a login opens the URL and signs in. They see an example project with a finished
   report. They write a new report from its source or their own upload (4 MB at most), follow its
   progress live, review it, accept or return it, and download it.
2. When nobody uses it, only Vercel and Supabase run; Modal bills nothing.
3. Work starts without anyone running a worker by hand.
4. The Modal URLs refuse requests that did not come through the signed-in front door.
5. A push to `main` deploys the demo after `ci` passes. The v1 jobs, including `airgap`, and the
   coverage gates are unchanged and green.
6. Spending is capped: an OpenRouter key with a credit limit, the Modal workspace budget, and a
   4 MB upload limit.
7. Progress follows a run within 2 s of each stage change (or, if spike S2 fails, within the 10 s
   heartbeat), and never stalls.

## 11. Architecture

```
browser ──HTTPS──▶ Vercel (always on)
                    ├─ static web app (web/dist) and /login
                    └─ middleware: checks the session cookie, then rewrites /api/* to Modal,
                       adding X-Remote-User, X-Corelata-Proxy-Secret, Modal-Key, Modal-Secret
                                   │
                                   ▼
                   Modal app "corelata" (each part scales to zero)
                    ├─ api      ASGI (corelata_api), 1 CPU; one container; LISTEN while awake
                    ├─ kick     web endpoint: starts a burst worker
                    ├─ worker   run_worker(burst=True); drains the queue, exits
                    ├─ cron     every 5 min: sweeps, then starts a worker if needed
                    ├─ purge    daily: deletes closed jobs older than the retention
                    └─ migrate, doctor, seed   run by hand or by the deploy job
                                   │
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
   Supabase Postgres      Supabase Storage (S3 API)   OpenRouter
   (session pooler,       bucket corelata-files       gpt-4.1-mini (gate, writer, editor)
    IPv4, port 5432)                                  gemini-2.5-flash (standards check)
```

| Part | Runs | Cost when idle |
|---|---|---|
| Vercel project `corelata-demo` | always (the existing Pro team) | already paid |
| Supabase project `corelata-demo` | always | about $10/month (a second Micro compute; decision 22.3) |
| Modal `api`, `worker`, `kick` | on demand | $0, inside the workspace's included credit |
| Modal `cron`, `purge` | a few seconds of CPU every 5 min, once a day | cents per month |
| OpenRouter | per token | $0 |

There is no scorer, no GPU, no weights Volume and no scorer secret.

## 12. What is copied from Coglossa

Each item is copied, renamed (`COGLOSSA_` → `CORELATA_`, `coglossa` → `corelata`) and otherwise
left alone, apart from the divergences listed, which go into `docs/m19-followups.md`.

### 12.1 Engine and API

| Item | Corelata | Divergences |
|---|---|---|
| `storage.kind: s3` (`S3StorageConfig`, the discriminated union, `S3Storage` with path-style addressing and `when_required` checksums; one `DeleteObject` per key) | `engine/corelata/config.py`, `storage.py`; `boto3` in a new `s3` extra of `engine` and `api` | `S3Storage.list_keys` added (Corelata's `Storage` protocol has it; the worker uses it to clear stale exports). Env names `CORELATA_S3_ACCESS_KEY_ID`, `CORELATA_S3_SECRET_ACCESS_KEY`. Every storage call on an async path that still runs on the event loop (several in `service.py`, such as the upload's `put` and a rerun's `delete_prefix`; the plan lists each) moves into `asyncio.to_thread`: harmless for local storage, needed for S3 (**backport** check for Coglossa). |
| Tests on `moto` | `engine/tests/test_storage_s3.py` | `moto[s3]` in the engine's dev group only |
| `auth.proxy_secret_env` and `ProxySecretMiddleware` (constant-time compare, `/api/health` open) | `api/corelata_api/proxy.py`, `app.py` | Header `X-Corelata-Proxy-Secret`; message "this address only answers requests from the Corelata sign-in proxy". No `groups_header`, `admin_group` or `people_file` (no roles). |
| `worker.kick_url`, `kick_token_env`, `extra_headers_env`, `env_headers`; `HttpKicker` (5 s timeout, 2 s debounce, fire-and-forget) and `KickingQueue` | `engine/corelata/worker/kick.py`, `config.py`, `api/corelata_api/app.py` | `KickingQueue.defer` passes `priority` through (Corelata's discoveries use priority 1, R-M17-29). |
| `QueueStatus`, `queue_status`, `needs_worker` (live workers from `procrastinate_workers`) | `engine/corelata/worker/app.py` | Use Corelata's `_PENDING_SQL`, unchanged. |
| `validate_config` checks for the new variables; `doctor` lines for the bucket, the kick URL (never called) and the proxy secret | `config.py`, `doctor.py` | none |

All of it is off by default. `storage.kind: local` and its path, an unset kick URL and an unset
proxy secret behave exactly as today. The new settings are in operational sections, so
`config_hash` is unchanged. The air-gapped image installs no extra, so it carries no `boto3`
(`deploy/tests/check-app-image.sh` gains that check).

### 12.2 `deploy/hosted/`

| Coglossa | Corelata | Divergences |
|---|---|---|
| `modal/app.py`, `settings.py`, `check_app.py`, `requirements.txt`, `test_settings.py`, `conftest.py` | same | No `scorer`, `scorer_image`, weights Volume or `upload_weights.py`. Functions: `api`, `worker`, `kick`, `cron`, `purge`, `migrate`, `doctor`, `seed` (§13.5, §13.6). The app image copies `docs/examples/varna-port.txt` to `/etc/corelata/examples/`. `api.web_dir` is unset (Vercel serves the app). |
| `coglossa.hosted.yaml` | `corelata.hosted.yaml` | Corelata's config (§14) |
| `vercel/middleware.ts`, `lib/route.ts`, `lib/auth.ts`, tests, `vercel.json`, `build.sh`, `package.json`, `.vercelignore` | same | Env `CORELATA_USERS`, `CORELATA_SESSION_SECRET`, `CORELATA_API_ORIGIN`, `CORELATA_PROXY_SECRET`, `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET`; cookie `crl_session`; header `x-corelata-proxy-secret`. Accounts may carry groups, as in Coglossa, and `x-remote-groups` is still stripped and set, but Corelata ignores it. `vercel.json` adds the operator guide's sample `Content-Security-Policy` on every path; a test checks it matches the guide word for word, as `csp_proxy.py`'s test does. |
| `vercel/static/login.html` | same | "Corelata" title and heading; key `corelata.theme`; colours from M18's `tokens.css` (the same values). |
| `add-user.mjs` | same | Usage line names `CORELATA_USERS`. |
| `smoke.py`, `test_smoke.py` | same | Check 2 reads `GET /api/system/info` (Corelata has no `/api/me`) and expects `user == "ci"`. Check 6 is added: the example project exists (`GET /api/projects` through the site). Env `CORELATA_SMOKE_PASSWORD`, `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET`. |
| `README.md` | same | Corelata's names, no scorer, the seed step, §16's steps. |
| `.github/workflows/hosted.yml` | same | Adds `modal run …::seed` after the deploy. Skips with a notice without `MODAL_TOKEN_ID` or `VERCEL_TOKEN`, so forks and PRs stay green. |

CI gains Coglossa's two jobs, `hosted-web` (the front door's Vitest at 95 % and `tsc`) and
`hosted-modal` (`test_settings.py` and `check_app.py`, no Modal account). `ci-status` needs them
too.

## 13. What is Corelata's own

### 13.1 Progress: LISTEN through the session pooler

**Decision: the hosted API keeps its one `LISTEN` connection on the same Supabase session-pooler
URL as everything else, port 5432.** No direct connection.

- In session mode the pooler gives each client connection one server connection for the client's
  whole session, so `LISTEN` and the notifications it receives work as on a direct connection.
  The M14 follow-up is about transaction pooling (Supabase's port 6543), which the hosted config
  never uses.
- The direct connection (`db.<ref>.supabase.co`) is IPv6-only without Supabase's paid IPv4
  add-on, and would be a second connection string to manage.
- The worker and the service send `NOTIFY` inside their own transactions through the pooler, as
  on Postgres; a notification reaches every listener on the database.
- The connection exists only while the API container is awake. While it is down, or while it is
  reconnecting (1, 2, 4, 8, 16, then every 30 s), the feed polls every `api.progress_poll_s`.

**Verified by spike S2 (§18)** before anything is built on it. If S2 fails, the hosted demo accepts
heartbeat progress: with `api.progress_poll_s: 1.0` the heartbeat is
`max(1, min(1 × 10, 30))` = 10 s, so a stage change shows at most 10 s late. The hosted config then
sets `progress_poll_s: 0.5` (5 s), and a self-`NOTIFY` check at connect that logs when nothing
comes back is filed as a follow-up (it would also help a customer behind a transaction pooler).

### 13.2 The progress stream through Vercel

- The stream sends `retry: 3000`, the current progress at once, a `: keep-alive` comment every
  15 s (`HEARTBEAT_S`) while nothing changes, and closes after the terminal event. That is a
  different clock from the feed's database heartbeat in §13.1.
- Vercel's 120 s proxy limit: if it is an idle limit, the 15 s comments keep the stream open. If it
  caps a response's total length, Vercel ends the stream, the browser reconnects after 3 s, and
  the first event on the new stream carries the current state, so nothing is lost. If a reconnect
  itself fails, the page falls back to reading `GET /runs/{id}` every 3 s (unchanged behaviour).
- Spike S1 (§18) holds a stream open for 5 minutes through Vercel and records which case applies.
- An open stream keeps the API container awake (about $0.05/hour), and it closes when the run
  ends, as in Coglossa.

### 13.3 Uploads

Vercel refuses request bodies over about 4.5 MB (Coglossa's spike S1: 4 MiB passed, 4.4 MiB
failed). `api.max_upload_mb` is **4** on the demo. `GET /api/system/info` reports it, so M18's drop
area marks a larger file before sending it; anything that still reaches Vercel's limit gets
Vercel's own 413, which M18 shows as "too large for this server".

### 13.4 Worker limits under a burst worker

| Setting | v1 default | Hosted | Why |
|---|---|---|---|
| `worker.discovery_start_deadline_s` | 3600 | **600** | The kick starts a worker within seconds; if a kick is lost, the cron starts one within 5 minutes. Ten minutes covers two cron ticks and a cold start. A demo user learns of a stuck discovery in 10 minutes instead of an hour. The web's ceiling is then `max(10 min, 600 s + 15 s)` = 10 min 15 s. |
| `worker.discovery_deadline_s` | 600 | 600 | unchanged |
| `worker.stalled_after_s` | 900 | **120** | A worker container Modal stops (a timeout, a crash) leaves its heartbeat behind. After 120 s the cron's `needs_worker` sees the stalled job, and the next worker re-queues it. A cancel of such a run ends it at once after 120 s, not 15 minutes. procrastinate beats every 10 s, so a live worker is far inside the limit (Coglossa's default is 60 s with the same worker). |
| `worker.concurrency` | 2 | 4 | Runs and discoveries share the slots; discoveries are fetched first. |
| Modal `worker` | — | 2 CPU, 4 GiB, `max_containers=2`, `timeout=86400` | as Coglossa |

When no worker is running, the start limit is enforced by whoever looks first: the API's read of
the discovery, or the next worker's sweep or claim (M17). Nothing waits for a worker to fail a
discovery.

An orphaned cancel needs no new code. A burst worker that exits cleanly finishes its jobs and
removes its worker row. One that Modal stops leaves a stale heartbeat; once it is 120 s old a
cancel ends the run at once and closes the job (M17), and the stalled-job requeue skips it.

### 13.5 The cron and the daily purge

The v1 worker's periodic tasks (stalled requeue and orphan sweep every minute, the purge at
03:17) run only while some worker runs, which on the demo is rarely at those minutes. So:

- **`cron`** (every 5 minutes) first runs `sweep_orphans` and `expire_discoveries` directly against
  the database (both are plain functions over a `Database`), then spawns a worker when
  `needs_worker` says so (due jobs and no live worker, or stalled jobs).
- **`purge`** (`modal.Cron("17 3 * * *")`) runs `purge_closed_jobs` with
  `worker.job_retention_days`.

### 13.6 Demo data

**Decision: after deploy, an example project exists with a finished report.** The deploy job runs
`modal run deploy/hosted/modal/app.py::seed`. When no project named "Example: Varna port" exists, it
runs `corelata run --project "Example: Varna port" --statement STATEMENT
/etc/corelata/examples/varna-port.txt`, then spawns a worker. When the project exists, it does
nothing, so a redeploy never writes a second report. STATEMENT is a constant in `app.py`: "The port
of Varna's 2025 container expansion, financed by a state bank, is already raising traffic; shippers
and the port authority should plan for higher volumes." A demo then opens on a report to review,
while the presenter writes a new one live. Seeding costs one report's tokens, once.

## 14. The hosted config (`deploy/hosted/corelata.hosted.yaml`)

```yaml
# Hosted demo (docs/superpowers/specs/2026-10-20-corelata-design-system-and-hosted-demo.md).
# ${NAME} values come from the Modal Secret corelata-hosted when a container starts
# (deploy/hosted/modal/settings.py); no secret is in this file.
backends:
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    max_concurrency: 4
    timeout_s: 300
models:
  writer-model:            # the gate, the writer and the editor: the bench pair (M12–M17)
    backend: openrouter
    name: openai/gpt-4.1-mini
    context_window: 128000
    structured_output: json_schema
    max_output_tokens: 8192
    temperature: 0.2
  auditor-model:           # a different family for the standards check (spec §4.4)
    backend: openrouter
    name: google/gemini-2.5-flash
    context_window: 128000
    structured_output: json_schema
    max_output_tokens: 8192
    temperature: 0.1
roles:
  gate:     { model: writer-model }
  writer:   { model: writer-model }
  conveyor: { model: writer-model }
  auditor:  { model: auditor-model }
  profiler: { model: writer-model }
standards:
  default_pack: icd203-base   # packs_dir unset: the base pack built into the engine
pipeline:
  max_iterations: 2
database:
  url_env: CORELATA_DATABASE_URL
storage:
  kind: s3
  endpoint_url: ${CORELATA_S3_ENDPOINT}
  region: ${CORELATA_S3_REGION}
  bucket: corelata-files
worker:
  concurrency: 4
  stalled_after_s: 120
  discovery_start_deadline_s: 600
  kick_url: ${CORELATA_KICK_URL}
  kick_token_env: CORELATA_KICK_TOKEN
  extra_headers_env: { Modal-Key: CORELATA_MODAL_KEY, Modal-Secret: CORELATA_MODAL_SECRET }
api:
  max_upload_mb: 4
  progress_poll_s: 1.0
auth:
  mode: trusted_header
  header: X-Remote-User
  proxy_secret_env: CORELATA_PROXY_SECRET
  logout_url: /logout
```

- **Models:** the pair the real bench scored 8/8, 8/8, 4/4 on at M17 (`gpt-4.1-mini` for the gate,
  writer and editor; `gemini-2.5-flash` for the standards check). Coglossa's Gemma 4 and Qwen3.6
  have never been run against Corelata's strict schemas. `corelata doctor` and
  `corelata bench --scenarios real` against this config are part of M19's acceptance.
- **Standards:** the built-in `icd203-base`, no profiles of the customer's.
- **Integrations:** no `integrations.coglossa` (the Coglossa preview is behind its own front door).
  Coglossa export files can still be uploaded.
- **Logins** (§16 step 11): `demo` (shared for demo sessions), the owner's own login, and `ci` for
  the smoke test. All see every project.

## 15. Secrets

| Variable | Lives in | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | Modal Secret | A **new** key, `corelata-demo`, with a credit limit |
| `CORELATA_DATABASE_URL` | Modal Secret | The session-pooler URL, port 5432, with `?sslmode=require` |
| `CORELATA_S3_ACCESS_KEY_ID`, `CORELATA_S3_SECRET_ACCESS_KEY` | Modal Secret | Supabase Storage S3 keys (full access: server side only) |
| `CORELATA_S3_ENDPOINT`, `CORELATA_S3_REGION` | Modal Secret | From Supabase's S3 settings |
| `CORELATA_PROXY_SECRET` | Modal Secret and Vercel env | 32 random bytes, the same in both |
| `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET` | Modal Secret, Vercel env, GitHub secrets | The workspace proxy-auth token |
| `CORELATA_KICK_TOKEN` | Modal Secret | 32 random bytes |
| `CORELATA_KICK_URL` | Modal Secret | The deployed `corelata-kick` URL (step 8) |
| `CORELATA_SESSION_SECRET`, `CORELATA_USERS`, `CORELATA_API_ORIGIN` | Vercel env | |
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `CORELATA_SMOKE_PASSWORD`, `CORELATA_MODAL_KEY`, `CORELATA_MODAL_SECRET` | GitHub Actions secrets | The deploy job only |
| `CORELATA_SITE_URL`, `CORELATA_API_ORIGIN` | GitHub Actions variables | |

No secret is committed or printed. Values the owner creates go into
`~/.config/corelata/hosted.env` (mode 600, outside the repository), which the controller reads to
set the Modal Secret, the Vercel env and the GitHub secrets without echoing them.

## 16. Provisioning

**O** = the owner does or approves it. **C** = the controller does it with this machine's tools
(the Modal CLI signed in as `mrbonha`, the Supabase and Vercel connectors, `gh`).

| # | Who | Step |
|---|---|---|
| 1 | O | Approve this spec, the Supabase project's cost (decision 22.3) and a new OpenRouter key. One message is enough. |
| 2 | C | Spike S1 (Vercel stream length) on a throwaway Vercel project; delete it afterwards. |
| 3 | C, else O | Create the Supabase project `corelata-demo` in Coglossa's region, through the Supabase connector. If the connector needs a cost confirmation it cannot give, the owner creates it in the dashboard. |
| 4 | O | In the Supabase dashboard: Storage ▸ S3 Connection ▸ generate an access key pair; Connect ▸ copy the session-pooler URL (port 5432) with the database password; Database ▸ Connection pooling ▸ Pool Size 40. Put the values in `~/.config/corelata/hosted.env`. |
| 5 | C | Create the private bucket `corelata-files` (Storage SQL through the connector); run spike S2 against the pooler URL. |
| 6 | O | OpenRouter: create the key `corelata-demo` with a **$25** credit limit; add it to `hosted.env`. |
| 7 | O | Modal dashboard: create a proxy-auth token (Settings ▸ Proxy Auth Tokens) or reuse Coglossa's if its values are at hand; add both values to `hosted.env`. Check the workspace budget (decision 22.3). |
| 8 | C | Generate the proxy secret, kick token and session secret; `modal secret create corelata-hosted …` from `hosted.env` (kick URL as a placeholder); `modal run …::migrate`; `modal deploy …`; put the printed kick URL in the Secret; deploy again; `modal run …::doctor`. |
| 9 | C | Create the Vercel project `corelata-demo` from `deploy/hosted/vercel` (Root Directory empty) and set its env vars through the Vercel connector. |
| 10 | O | Create a Vercel token and a Modal token for CI (dashboards), and add them to `hosted.env`. |
| 11 | O, then C | Logins: the owner runs `node --experimental-strip-types deploy/hosted/add-user.mjs demo` and the same for their own name, and adds the printed lines to `hosted.env`, so their passwords never pass through the controller. The controller generates the `ci` password, makes its line, sets `CORELATA_USERS` in Vercel and `CORELATA_SMOKE_PASSWORD` in GitHub. |
| 12 | C | `gh secret set` for every GitHub secret in §15 and `gh variable set` for the two variables. |
| 13 | C | Run `hosted.yml` by hand (`workflow_dispatch`): migrate, deploy, seed, front door, smoke. Then the manual end-to-end check (§19) and `corelata doctor` plus `corelata bench --scenarios real` against the hosted config; post the results on CRL-42. |
| 14 | O | Try the demo with the `demo` login and say yes before the URL is shared. |

## 17. Operations

- **Deploy:** `hosted.yml` on push to `main` after `ci` passes, or by hand. Migrations run first;
  the seed runs after the deploy.
- **Rollback:** deploy an earlier commit. Migrations only move forward.
- **Backups:** Supabase's daily backups. The bucket has none, which is acceptable for a demo.
- **Logs:** Modal (one day on Starter) and Vercel.
- **Checks:** `modal run …::doctor`; the smoke test after every deploy.
- **Revoking access:** remove a user from `CORELATA_USERS`, or rotate `CORELATA_SESSION_SECRET` to
  sign everyone out; redeploy the front door.
- **Starting clean:** Corelata has no delete route. To clear demo data the controller truncates
  the tables and the bucket through the Supabase connector, then runs the seed again; the README
  holds the exact statements.
- **Spending limits,** all set before the URL is shared: the OpenRouter key's $25 credit limit; the
  Modal workspace budget; `api.max_upload_mb: 4`.

## 18. Spikes, done first

| Spike | Question | Pass | If it fails |
|---|---|---|---|
| S1, Vercel stream length | Through Coglossa's middleware on a throwaway project, does a 5-minute SSE response with a comment every 15 s stay open, or is it cut at 120 s? | Either result is acceptable; it decides which §13.2 case the README describes. A reconnect must deliver the current state. | none needed |
| S2, LISTEN through the session pooler | Two connections to the pooler URL: `LISTEN corelata_run` on one, `NOTIFY corelata_run, '<uuid>'` from the other, ten times. Then, with the API deployed, the API log shows "progress listener connected" and a run's stage changes reach `GET /runs/{id}/events` through the site. | Every notification arrives within 2 s; each stage change shows within 2 s of its stage row's `finished_at`. | §13.1's fallback: heartbeat progress, `progress_poll_s: 0.5`, a follow-up for the self-`NOTIFY` check |
| S3, procrastinate through the pooler | Coglossa's S2 already proved migrations, defer and burst fetching through Supabase's session pooler. Corelata repeats only `migrate` and one queued run. | Both work. | Stop and report: this is Coglossa's working setup. |

## 19. Testing (M19)

| Layer | Scope |
|---|---|
| Engine and API unit tests (95 %) | `S3Storage` on moto, including `list_keys` and the not-found message; the config union and validation of every new field; `ProxySecretMiddleware`; `HttpKicker` (success, failure, debounce) with a fake transport; `KickingQueue` passing `priority`; `queue_status` and `needs_worker` on a real Postgres; `doctor` lines; storage calls moved into threads |
| Front door (Vitest, 95 %) | Coglossa's tests, renamed: password check, cookie signing and expiry, header stripping and setting, CSRF origin check, routing decisions; the CSP header in `vercel.json` matches the guide's sample |
| Modal app (CI, no account) | `check_app.py`: the function list and labels, and an import as Modal's container does; `test_settings.py`: config rendering, missing values, the kick token check |
| Smoke (after each deploy) | Sign in as `ci`; `/api/system/info` through the site names `ci`; Modal refuses a request without its token; the API refuses one without the proxy secret; health answers; the example project exists |
| End to end (by hand, recorded in the PR) | Sign in as `demo`; open the example report; upload `varna-port.txt` to a new project; suggest value; write the report; watch the steps; review; return with a note; the revised report completes; download DOCX; sign out |
| v1 | Every existing job unchanged, `airgap` included; the app image carries no `boto3` |

---

## 20. Out of scope (each becomes a follow-up if wanted)

- Layouts for phone-sized screens.
- User roles, teams and per-user data separation (Coglossa's CGL-26). Every signed-in person sees
  every project.
- Renaming or deleting projects (Corelata has no such routes); the sidebar has no ⋯ menu.
- Uploads larger than 4 MB on the demo (direct-to-storage upload).
- A self-`NOTIFY` check in `RunListener` (only if S2 fails).
- Any change to `report.css`, the rendered documents or the frame policy.
- Fetching from Coglossa on the demo.
- A custom domain, unless the owner asks (decision 22.5).
- Extracting a shared package (CRL-3).

## 21. Risks

| Risk | Mitigation |
|---|---|
| A behaviour M9–M17 pinned changes during the restyle | §2.6 lists them; their tests keep their assertions; the whole-branch review checks the list |
| The report frame does not follow the theme in some browser | The theme is set by the bridge, not inferred, and the Playwright dark-mode check reads the frame's computed colours |
| First request after idle is slow (about 5 s for the API) | The web app shows loading states; keeping the API warm is a later switch (about $15/month) |
| LISTEN does not work through the pooler | Spike S2 first; heartbeat progress is the designed fallback |
| A queued job sits unnoticed | A kick on every defer, the 5-minute cron, the 10-minute discovery start limit |
| Supabase pooler connection limits | One API container, at most two workers, Pool Size 40, as Coglossa |
| The Modal workspace budget is shared with Coglossa's GPU scorer, so one product's use can stop the other | Corelata runs CPU only; the owner checks the budget (decision 22.3) |
| Demo visitors see each other's projects and the demo fills up | Stated in §20; the README's "starting clean" steps |
| The demo's hosted models outperform the customer's own models | The presenter says so; the bench numbers for local models are on the tickets |

## 22. Decisions for the owner

Each has a recommendation; everything else in this spec is decided.
Taken 2026-10-20 for M18: 1 (Noto Sans) and 6 (the report follows the app's theme), as recommended. 2 to 5 were taken on 2026-10-20 for M19: 2 and 4 as recommended, 3 and 5 as §23 records (see §23).

1. **Bundle Noto Sans in Corelata.** Recommended: yes, only `@fontsource/noto-sans@5.3.0`, the
   package and version the customer already vetted for Coglossa, so the two products share a
   typeface. It reverses M4b's "system fonts only". Without it, M18 uses the system font stack.
2. **Demo models.** Recommended: the bench pair, `openai/gpt-4.1-mini` with
   `google/gemini-2.5-flash` for the standards check (8/8 on the real bench at M17). Coglossa's
   Gemma 4 / Qwen3.6 pair is untested on Corelata and closer to what an air-gapped customer runs;
   it can follow after a bench run.
3. **A separate Supabase project and the shared Modal budget.** Recommended: a new Supabase project
   `corelata-demo` (about $10/month for its compute), not a second database inside Coglossa's
   project, so the two demos can be reset and torn down apart. Keep the Modal workspace budget at
   $30 unless Coglossa's scorer use already comes close to it; Corelata adds only CPU time.
4. **A seeded example report on deploy.** Recommended: yes (§13.6). It costs one report's tokens
   per fresh database and gives every demo something to open at once.
5. **The URL.** Recommended: start on the Vercel project's own `*.vercel.app` address; add
   `demo.corelata.com` later if the owner wants a branded link.
6. **The report page follows the app's theme.** Recommended: yes (§0.4, §5.5). The alternative is a
   white "paper" page in both themes, which is closer to the printed DOCX but glares in dark mode.

## 23. Amendments from the owner's decisions and spike S2

Taken 2026-10-20, after the sections above were written. Each item names the text it replaces;
where this section and §10 to §22 disagree, this section wins. The M19 plan
(`docs/superpowers/plans/2026-10-20-m19-hosted-demo.md`) is written against it.

### 23.1 Supabase: Coglossa's project, Corelata's own database and bucket

Replaces decision 22.3 and the Supabase parts of §11, §15, §16 and §21.

- **No new Supabase project.** Corelata uses Coglossa's project `coglossa-preview` (ref
  `kvqokbgrftgmgcocclgu`, region ca-central-1). The §11 table's "about $10/month" row is gone:
  the demo adds no Supabase cost.
- **Its own database, `corelata`,** in that project, reached through the same session pooler on
  port 5432 (`aws-1-ca-central-1.pooler.supabase.com`, user `postgres.<ref>`, path `/corelata`,
  `?sslmode=require`). A separate database is needed because both products use procrastinate's
  tables (`procrastinate_jobs` and the rest), which cannot be shared.
- **Its own bucket, `corelata-files`,** private, beside `coglossa-files`.
- The S3 key pair and the database password are Coglossa's existing project-wide values.
- The database and the bucket already exist: the controller created them on 2026-10-20.
- **Starting clean** (§17) truncates only database `corelata`'s tables and empties only bucket
  `corelata-files`. **Teardown** is `DROP DATABASE corelata` and deleting that bucket. Nothing in
  M19, its scripts or its runbook may ever touch Coglossa's database or `coglossa-files`;
  `deploy/hosted/README.md` says so, and the start-clean script refuses any other database or
  bucket.
- The pooler and the project's connection limit are now shared by the two demos, so §21's
  "Supabase pooler connection limits" risk covers both together.

### 23.2 OpenRouter: the existing key

Replaces §15's `OPENROUTER_API_KEY` note and §16 step 6. The existing key, which already has a
$25 credit limit, is used; there is no new key. On the controller's machine it is
`CORELATA_OPENROUTER_KEY`; in the Modal Secret it is `OPENROUTER_API_KEY`.

### 23.3 Logins

Replaces §14's "Logins" bullet, §16 step 11 and the `demo` login in §16 step 14 and §19.

- `people-first`: the demo team's shared login. It carries the same pbkdf2 hash as on Coglossa's
  preview, so one password works on both demos.
- `ci`: the smoke test's login.
- There is no `demo` login and no owner login. The §19 end-to-end check signs in as
  `people-first`.

### 23.4 The URL

Decision 22.5, as recommended: the `*.vercel.app` address of the Vercel project `corelata-demo` in
the team `bonham-technologies`. No custom domain.

### 23.5 Deploy by hand

Replaces §16 and part of §10.5, §15 and §17.

- The controller deploys from its own machine, as Coglossa's preview is deployed: the Modal CLI
  (signed in as `mrbonha`) and the Vercel CLI (signed in).
- The Modal proxy-auth token is Coglossa's workspace token, reused (`CORELATA_MODAL_KEY`,
  `CORELATA_MODAL_SECRET`). Corelata's own proxy secret is new, so a caller holding the shared
  token still cannot use Corelata's API without it.
- `.github/workflows/hosted.yml` is still copied. It skips with a notice without
  `MODAL_TOKEN_ID` and `VERCEL_TOKEN`; Coglossa's repository has no deploy secrets either.
  Deploying on push waits on CI tokens that only the owner can create; that is a follow-up in
  `docs/m19-followups.md`, and §15's GitHub rows apply only once the owner adds them.
- Success criterion §10.5 becomes: "`hosted.yml` deploys on push once the owner adds CI tokens;
  until then the controller deploys by hand. The v1 jobs, including `airgap`, and the coverage
  gates are unchanged and green."
- §16's step list is replaced by the M19 plan's "Provisioning and deploy" section, which the
  controller carries out.

### 23.6 Spike S2 passed

Settles §13.1 and the first half of §18's S2.

- Through the session pooler, `CREATE DATABASE corelata` worked, and `LISTEN`/`NOTIFY` on
  `/corelata` delivered 10 of 10 notifications, worst 0.117 s and mean 0.068 s, against a 2 s
  target. A `NOTIFY` sent inside a transaction was delivered too.
- So §13.1's main path stands: the API listens through the session pooler. There is no fallback,
  `api.progress_poll_s` stays 1.0, and there is no self-`NOTIFY` follow-up (§20's item is dropped).
- S2's second half (the API log shows "progress listener connected", and a run's stage changes
  reach `GET /api/runs/{id}/events` through the site within 2 s of each stage's `finished_at`)
  remains part of M19's final acceptance.

### 23.7 Spike S1

Replaces §16 step 2. S1 (the Vercel stream length) runs during provisioning on the real
`corelata-demo` project, not on a throwaway one. Either result is acceptable (§13.2); it decides
which case `deploy/hosted/README.md` describes.

### 23.8 Decisions 22.2 and 22.4

Taken as recommended: the bench pair (`openai/gpt-4.1-mini` for the gate, writer and editor,
`google/gemini-2.5-flash` for the standards check), and the seeded example report (§13.6).
