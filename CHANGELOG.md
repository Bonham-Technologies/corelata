# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

- Releases publish only from a tag on main, build and test with a read-only token, and ship a Postgres image pinned by digest (recorded in the bundle manifest); every CI job has a timeout. Ticket: CRL-115
