# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

- Pack loading, reference-document reads, the web app's file lookups and the doctor's config, prompt and pack checks run off the event loop, so a slow packs directory no longer stalls other requests. Ticket: CRL-113
- An unreachable Coglossa and an unknown pack no longer reveal server addresses or paths to the client (the log keeps them); a Coglossa error answer is read only to 64 KB, and an import is held to the upload limit. Ticket: CRL-114
- Releases publish only from a tag on main, build and test with a read-only token, and ship a Postgres image pinned by digest (recorded in the bundle manifest); every CI job has a timeout. Ticket: CRL-115
- `GET /api/system/doctor` no longer sends test completions unless asked: an API caller that wants them now passes `probe=true`. Concurrent or repeated probes within 30 s share one run. Ticket: CRL-112
- Uploading a file, or importing a Coglossa run, that the project already has no longer adds a second copy: the API answers 200 with the existing source, flagged `already_in_project`, and the upload chip says "already in this project". Ticket: CRL-126
