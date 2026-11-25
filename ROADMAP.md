# Roadmap

What we're working on, what's next, and what shipped recently. Plans change; the
[changelog](CHANGELOG.md) is the record of what actually shipped.

## Now

- The model-server check (`corelata doctor` in the web app) probes only when asked, and
  concurrent requests share one run.
- Release hardening: only tags on `main` publish, the write token is limited to the
  publish step, and the bundled Postgres image is pinned by digest.
- Quote-anchored evidence turned on by default in bundle installs and the demo stack.

## Next

- Opening a claim or a run's trace stays fast with very large sources, and no longer
  slows other requests.
- Uploading a file that is already in the project no longer creates a second copy.
- Clear "not found" pages for links to reports or projects that no longer exist.
- Malformed text in a request gets a clear validation error instead of an internal one.
- The top bar reflows at 400% zoom.
- A README written for first-time visitors, with a quick start at the top.
- Smaller fixes: `HEAD` requests on the app and health check, an empty sidebar search,
  review event ordering, export rendering off the worker's event loop, project-memory
  settings per profile, and a quieter web test run.

## Recently shipped

- Pack loads and file lookups run off the API's event loop.
- Error messages no longer include the address or file paths of a connected Coglossa.
- corelata.com rebuilt, with its checks running in CI.
- Security headers on every response, and a sandboxing content policy for HTML reports.
- ICD 206 source reference citations and a source summary section in every report.
- Offline OCR for scanned PDF pages, marked as such in the provenance.
- Documentation brought up to date for the public repository.
