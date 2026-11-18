# corelata.com

The public site for Corelata (CRL-81): one static page with a writeup and a recorded walkthrough,
a sample report page, and a 404 page. Plain HTML and CSS on the Bonham Technologies design system (below), with no
build step, no script and no third-party requests at run time. The fonts (Archivo and IBM Plex
Mono, latin subsets) are self-hosted under the SIL Open Font License; their licences are next to
them in `public/assets/fonts/`.

| Path                           | What it is                                                                                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `public/`                      | everything Vercel serves: `index.html`, `sample/index.html`, `404.html`, `robots.txt`, `sitemap.xml`, the favicons and `og.png` (1200x630) |
| `public/assets/site.css`       | the one stylesheet                                                                                                                         |
| `public/assets/walkthrough/`   | the screenshots (WebP at 1280 and 720 px), `walkthrough.webm`, its poster and captions (`walkthrough.vtt`)                                 |
| `public/sample/files/`         | a run's exports, copied verbatim: `report.html`, `report.md`, `report.docx`, `trace.json`                                                  |
| `vercel.json`                  | the Vercel project config: headers, CSP, `ignoreCommand`                                                                                   |
| `check.mjs`                    | the site check (below)                                                                                                                     |
| `tools/record-walkthrough.mjs` | records the walkthrough against a local dev stack                                                                                          |
| `tools/og.html`                | the Open Graph card that `public/og.png` is rendered from                                                                                  |

Every change under `site/` is merged by the owner (`ap-owner-merge`), and `.github/CODEOWNERS`
names the owner for `site/`.

The repository went public on 2026-11-18 (CRL-80). The Licence section links it, and that is the
only GitHub link the check allows (`REPO_URL` in `check.mjs`).

## Design

The site is built on the Bonham Technologies design system (the parent brand at bonham.tech): warm
paper and ink tokens with a Daylight (default) and a Night theme that follows the reader's system,
Archivo for text, IBM Plex Mono for technical content only (step numbers, figures, code), square
corners, hairlines, no shadows or gradients. Safety orange (`--signal-fill`) is the action colour:
one primary button per view, and nothing else is orange.

Corelata's own identity inside that system (owner, 2026-11-17):

- **Accent: plum** (`--product-accent`, `#6b3f86` Daylight, `#c9a3e6` Night). It colours the square
  in the lockup, eyebrows, link underlines and the threads. It never styles a button.
- **Motif: source threads.** Several sources tied by thin lines to the one statement they support:
  the drawing in the hero (`.threads`, an inline SVG coloured from `site.css`, because the CSP
  allows no inline style), the rule under the headline's key word, and the short rule before each
  point.
- **Lockup:** accent square, `CORELATA`, "by Bonham Technologies". There is no logo mark; the
  favicon is the motif on paper.
- The parent's terrain imagery (mountains, ridgeline, contours) and forest green stay on
  bonham.tech and are not used here.

`og.png` is `tools/og.html` rendered in Chromium at 1200 × 630; `apple-touch-icon.png` and
`favicon.ico` (16, 32 and 48 px) are `public/favicon.svg` rendered the same way.

## Check

    make site-check        # or: node site/check.mjs

Node 22, with Playwright and axe from `web/node_modules` (`cd web && pnpm install` first); no other
dependency. It serves `public/` on a free local port with the headers `vercel.json` sets and fails
on any of these:

- an internal link, fragment, image, `srcset` candidate, poster, track, video, stylesheet or font
  reference that does not resolve;
- a page without `lang`, `<title>`, a meta description, a canonical URL on https://corelata.com/
  or exactly one `<h1>` (the verbatim export `sample/files/report.html` needs only `lang`, a
  title and a canonical tag, the one line added to the copy);
- a request that leaves the site, a Content-Security-Policy violation, a console error or an
  HTTP error;
- an axe violation (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`) or sideways scrolling, on every
  page at 1280 px and at 360 px;
- a home page without exactly one `application/ld+json` block that parses and holds an
  `Organization` (name, `url` https://bonham.tech/, an https `logo`) and a `SoftwareApplication`
  (name, `url` https://corelata.com/, description, category, operating system, the Apache-2.0
  `license` URL and the Organization as `publisher`; an `offers`, if present, needs a price and a
  currency);
- anything that keeps the site out of search results: an `X-Robots-Tag` header in `vercel.json`,
  a `robots.txt` that disallows `/`, or a `noindex` meta tag on any page but `404.html`;
- a sitemap entry without a page, `robots.txt` without the sitemap, an `og.png` that is not
  1200x630, `public/` over 6 MB, or a `vercel.json` without the security headers, a
  `frame-ancestors 'none'` CSP on every page or the `ignoreCommand`.

It uses `/opt/pw-browsers/chromium` when it exists (cloud sessions), otherwise `CHROMIUM_PATH` or
Playwright's own browser. CI runs it as the `site` job on every pull request and every push to
`main`, and `ci-status` requires it.

## Deploy

The Vercel project's root directory is `site/`. There is no build: `vercel.json` sets an empty
build and install command and serves `public/`. `ignoreCommand` is
`git diff --quiet HEAD^ HEAD -- .`, run in `site/`, so a push to `main` that does not change
`site/` skips the deploy (exit 0 skips, exit 1 builds; a first deploy with no parent commit
builds). The project needs no environment variables and no secrets.

Headers on every response: HSTS (two years, subdomains), `nosniff`, a strict referrer policy, a
Permissions-Policy that turns off every device API (fullscreen stays allowed for the video),
`X-Frame-Options: DENY`, COOP and CORP `same-origin`. The pages' CSP is
`default-src 'self'; script-src 'none'; style-src 'self'; ...; frame-ancestors 'none'`; the
verbatim `sample/files/report.html` gets `default-src 'none'` with its inline stylesheet allowed
by its SHA-256 hash (the engine's `report.css`). If that export is replaced by one rendered with a
changed `report.css`, update the hash in `vercel.json`; `check.mjs` reports the CSP violation.

## Owner steps

1. Create the Vercel project for this repository with **Root Directory `site/`**, framework
   preset "Other", and **production branch `main` only**. Do not add environment variables.
2. Keep **Git Fork Protection** on (Project Settings → Git), so a pull request from a fork never
   deploys without approval.
3. Add **corelata.com** to the project, and **www.corelata.com** as a redirect to corelata.com.
4. DNS is at **Porkbun**: add the records Vercel shows for the apex and `www`.
5. Turn on the **registrar lock** (transfer lock) for corelata.com at Porkbun.
6. Use **passkeys or 2FA** on the GitHub, Vercel and Porkbun accounts that control the site.
7. Confirm whether the Vercel team needs **Pro** for a commercial site (Hobby is for
   non-commercial use).
8. In the repository's Actions settings, require **approval before running workflows for outside
   contributors**.

## How the demo and the sample were made

Both are real product output from Corelata 0.1.8 running locally with its synthetic test model
(`corelata fake-openai`), which `api/devstack.py` starts. No language model is involved; the pages
say so. The hosted demo's seeded example (a real-model run) was not used: this session has no
access to the hosted demo.

1. Start a throwaway stack on a free port:
   `cd api && uv run python devstack.py --host 127.0.0.1 --port <free port> --web-dir ../web/dist`
   (after `cd web && pnpm build`; it needs `CORELATA_TEST_DATABASE_URL`).
2. Record the walkthrough with the hosted demo's seed (the source `docs/examples/varna-port.txt`
   and the statement in `deploy/hosted/modal/settings.py`):
   `node site/tools/record-walkthrough.mjs http://127.0.0.1:<port> <out> docs/examples/varna-port.txt "<statement>"`.
   Playwright's `recordVideo` needs the ffmpeg build its version expects; where only an older one
   is installed, point `PLAYWRIGHT_BROWSERS_PATH` at a directory whose `ffmpeg-<n>/ffmpeg-linux`
   links to a system ffmpeg with libvpx. The script prints each step's time, which the captions
   in `walkthrough.vtt` follow. The writing step takes under a second on the synthetic model, so
   the in-progress screenshot is sometimes missed; run it again on a fresh stack.
3. Convert: `convert <png> -quality 82 -define webp:method=6 <name>-1280.webp` (and
   `-resize 720x -quality 80` for `-720`), and
   `ffmpeg -i walkthrough-raw.webm -vf scale=960:750:flags=lanczos -c:v libvpx-vp9 -b:v 0 -crf 34 -an walkthrough.webm`.
4. The sample run, on a stack whose config adds `audit: {store_llm_io: false}` so the trace
   carries no prompts or model replies (the samples are published): a second project with `varna-port.txt` and a `trade-note.txt` whose text ends
   with the synthetic model's `UNSOURCED` marker, started through the API with the same
   statement. Its exports come from `GET /api/runs/{id}/exports/{name}`, the findings from
   `GET /api/runs/{id}/findings` (iteration 0, verdict `fail`), and the printed trace from
   `corelata trace <dir>` and `corelata trace <dir> --claim c0` on the exported directory. The
   Process screenshot (`07-process`) is that run's review screen.
