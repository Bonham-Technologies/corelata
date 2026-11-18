# Security Policy

## Supported Versions

Corelata ships as an offline bundle attached to
[GitHub Releases](https://github.com/Bonham-Technologies/corelata/releases) (`v0.1.1` and later;
`v0.1.0` is withdrawn). Only the latest release and the current default branch receive security
fixes.

## Reporting a Vulnerability

Please **do not** open a public issue for security problems. Report privately via
[GitHub Security Advisories](https://github.com/Bonham-Technologies/corelata/security/advisories/new).

Include reproduction steps and the version you tested (the bundle version from `corelata --version`
or `/api/health`). You should hear back within a few business days; please allow a reasonable window
for a fix before public disclosure.

## Scope notes

Corelata is deployed as an offline Docker Compose bundle on the customer's network and talks only to
the model servers named in its configuration (and, when configured, a Coglossa instance). In scope:
anything in the engine, API, web app, worker or bundle scripts that could expose source material,
reports or traces to the wrong user, run code from a report or source document, send data anywhere
the configuration does not name, or let a model reply bypass the standards audit. Prompt-injection
findings against the gate, writer, conveyor or auditor are in scope. Out of scope: the security of
the customer's own model servers and reverse proxy.
