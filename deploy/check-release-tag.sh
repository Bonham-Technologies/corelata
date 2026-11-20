#!/usr/bin/env bash
# The release workflow's gate (CRL-115): a tag v<version> publishes only when it names the
# package version and the tagged commit is on main.
#   deploy/check-release-tag.sh v0.1.9 [main-ref]   (main-ref defaults to origin/main)
# Run it in a clone with main's history (actions/checkout with fetch-depth: 0).
set -euo pipefail
die() { echo "error: $*" >&2; exit 1; }
tag=${1:?usage: deploy/check-release-tag.sh <tag> [main-ref]}
main=${2:-origin/main}
repo=$(cd "$(dirname "$0")/.." && pwd)

[[ "$tag" == v* ]] || die "tag $tag does not start with v"
pkg=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$repo/engine/corelata/__init__.py")
[ "${tag#v}" = "$pkg" ] \
  || die "tag $tag does not match engine/corelata/__init__.py version $pkg; bump the package version first"
commit=$(git -C "$repo" rev-parse --verify --quiet "$tag^{commit}") || die "no tag $tag in this clone"
git -C "$repo" rev-parse --verify --quiet "$main^{commit}" >/dev/null || die "no $main in this clone"
git -C "$repo" merge-base --is-ancestor "$commit" "$main" \
  || die "tag $tag ($commit) is not on $main; tag a commit that is merged into main"
echo "ok: $tag is version $pkg at $commit, on $main"
