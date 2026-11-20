# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

- Pack loading, reference-document reads, the web app's file lookups and the doctor's config, prompt and pack checks run off the event loop, so a slow packs directory no longer stalls other requests. Ticket: CRL-113
- `GET /api/system/doctor` no longer sends test completions unless asked: an API caller that wants them now passes `probe=true`. Concurrent or repeated probes within 30 s share one run. Ticket: CRL-112
