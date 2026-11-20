# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

- `GET /api/system/doctor` no longer probes the model servers unless asked (`probe=true`), and concurrent or repeated probes within 30 s share one run. Ticket: CRL-112
