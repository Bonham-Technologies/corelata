#!/usr/bin/env bash
# Builds the front door's site into deploy/hosted/vercel/public: the web app plus the login page.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
(cd "$root/web" && pnpm install --frozen-lockfile && pnpm build)
rm -rf "$here/public"
mkdir -p "$here/public"
cp -R "$root/web/dist/." "$here/public/"
cp "$here/static/login.html" "$here/public/login.html"
cp "$here/static/robots.txt" "$here/public/robots.txt"
