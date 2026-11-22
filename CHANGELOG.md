# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

- At 400% zoom (320 CSS px wide) the top bar now wraps onto extra lines and scrolls away with the page instead of clipping "Your projects" and covering the page, and the projects sidebar opens just below it (WCAG 1.4.10 Reflow). Ticket: CRL-129
- A request whose text holds an unpaired UTF-16 surrogate (as pasted from a broken export) now answers 422 naming the field instead of 500, and validation answers no longer echo the submitted input. Ticket: CRL-128
- Pack loading, reference-document reads, the web app's file lookups and the doctor's config, prompt and pack checks run off the event loop, so a slow packs directory no longer stalls other requests. Ticket: CRL-113
- An unreachable Coglossa and an unknown pack no longer reveal server addresses or paths to the client (the log keeps them); a Coglossa error answer is read only to 64 KB, and an import is held to the upload limit. Ticket: CRL-114
- Releases publish only from a tag on main, build and test with a read-only token, and ship a Postgres image pinned by digest (recorded in the bundle manifest); every CI job has a timeout. Ticket: CRL-115
- `GET /api/system/doctor` no longer sends test completions unless asked: an API caller that wants them now passes `probe=true`. Concurrent or repeated probes within 30 s share one run. Ticket: CRL-112
- Opening a claim's provenance or a run's trace no longer stalls the server while a large source is read: a claim read fetches only the passages it cites, the trace counts each source's passages in the database, and loading a whole source happens off the event loop. Ticket: CRL-124
- Uploading a file, or importing a Coglossa run, that the project already has no longer adds a second copy: the API answers 200 with the existing source, flagged `already_in_project`, and the upload chip says "already in this project". Ticket: CRL-126
