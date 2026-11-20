# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

- Pack loading, reference-document reads, the web app's file lookups and the doctor's config, prompt and pack checks run off the event loop, so a slow packs directory no longer stalls other requests. Ticket: CRL-113
- Releases publish only from a tag on main, build and test with a read-only token, and ship a Postgres image pinned by digest (recorded in the bundle manifest); every CI job has a timeout. Ticket: CRL-115
