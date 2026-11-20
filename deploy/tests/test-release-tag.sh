#!/usr/bin/env bash
# deploy/check-release-tag.sh (CRL-115) against a throwaway repository: a tag on main passes; a
# tag on an unmerged branch, a tag that does not name the package version and a missing tag fail.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

git init -q -b main "$work/origin"
cd "$work/origin"
git config user.email test@example.invalid
git config user.name test
mkdir -p deploy engine/corelata
cp "$here/../check-release-tag.sh" deploy/
echo '__version__ = "1.2.3"' >engine/corelata/__init__.py
git add -A && git commit -q -m "release 1.2.3"
git tag v1.2.3
git checkout -q -b feature
echo "# work in progress" >>engine/corelata/__init__.py
git commit -q -am "unmerged"
git tag v1.2.3-branch
git checkout -q main
git clone -q "$work/origin" "$work/clone"
cd "$work/clone"
git fetch -q --tags origin

deploy/check-release-tag.sh v1.2.3 >/dev/null || fail "a tag on main was refused"
out=$(deploy/check-release-tag.sh v1.2.4 2>&1) && fail "a tag naming another version passed"
[[ "$out" == *"does not match"* ]] || fail "wrong version message: $out"
# the branch commit carries version 1.2.3 too, so only the ancestry check can stop it
git tag -f v1.2.3 "$(git rev-parse v1.2.3-branch)" >/dev/null
out=$(deploy/check-release-tag.sh v1.2.3 2>&1) && fail "a tag off main passed"
[[ "$out" == *"is not on origin/main"* ]] || fail "wrong ancestry message: $out"
# a tag that names the version but is not in the clone (the version check alone would pass)
git tag -d v1.2.3 >/dev/null
out=$(deploy/check-release-tag.sh v1.2.3 2>&1) && fail "a missing tag passed"
[[ "$out" == *"no tag v1.2.3"* ]] || fail "wrong missing-tag message: $out"
echo "ok: check-release-tag.sh"
