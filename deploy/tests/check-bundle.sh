#!/usr/bin/env bash
# Checks a built bundle: its transfer checksum, its own SHA256SUMS, every file the operator
# guide promises, the versions in the compose files, the images' tags, the SBOMs, and that the
# compose files resolve. Usage: deploy/tests/check-bundle.sh corelata-V-linux-amd64.tar
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tar_file=$(cd "$(dirname "${1:?usage: check-bundle.sh TAR}")" && pwd)/$(basename "$1")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail() { echo "FAIL: $(basename "$tar_file"): $*" >&2; exit 1; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

(cd "$(dirname "$tar_file")" && sha256 -c "$(basename "$tar_file").sha256" >/dev/null) \
  || fail "the .sha256 file does not match"
tar -xf "$tar_file" -C "$work"
dirs=("$work"/corelata-*)
if [ ${#dirs[@]} -ne 1 ] || [ ! -d "${dirs[0]}" ]; then fail "must extract to one corelata-<version>/ directory"; fi
b=${dirs[0]}
version=$(cat "$b/VERSION")
[ "$(basename "$b")" = "corelata-$version" ] || fail "the directory and VERSION disagree"
[ "$(basename "$tar_file")" = "corelata-$version-linux-amd64.tar" ] || fail "the file name and VERSION disagree"
(cd "$b" && sha256 -c SHA256SUMS >/dev/null) || fail "SHA256SUMS does not verify"
# SHA256SUMS lists every shipped file (and only those), so a file added later cannot go unchecked
(cd "$b" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort) >"$work/shipped.txt"
sed 's/^[^ ]*  //' "$b/SHA256SUMS" | LC_ALL=C sort >"$work/listed.txt"
diff "$work/shipped.txt" "$work/listed.txt" >&2 || fail "SHA256SUMS does not list exactly the shipped files (diff above)"
for f in install.sh backup.sh restore.sh; do [ -x "$b/$f" ] || fail "$f is missing or not executable"; done
for f in compose.yaml compose.demo.yaml config/corelata.example.yaml config/corelata.demo.yaml \
  config/packs.example/icd203-base/pack.yaml examples/varna-port.txt \
  operator-guide.md manifest.json images/app.tar images/postgres.tar \
  sbom/app.cdx.json sbom/postgres.cdx.json sbom/web.cdx.json; do
  [ -s "$b/$f" ] || fail "$f is missing or empty"
done
# the files install.sh creates and the operator edits are not shipped, so SHA256SUMS never names them
for f in config/corelata.yaml config/packs .env; do [ ! -e "$b/$f" ] || fail "$f must not be in the bundle"; done
if grep -q 'CORELATA_VERSION' "$b"/compose*.yaml; then fail "a compose file still names CORELATA_VERSION"; fi
grep -q "corelata/app:$version" "$b/compose.yaml" || fail "compose.yaml does not name corelata/app:$version"
[ -z "$(find "$b" -name '._*' -o -name '.DS_Store')" ] || fail "macOS metadata files are in the bundle"
for d in config examples; do # the containers (uid 10001) read them through bind mounts
  [ -z "$(find "$b/$d" ! -perm -o=r)" ] || fail "a file under $d/ is not world-readable"
  [ -z "$(find "$b/$d" -type d ! -perm -o=x)" ] || fail "a directory under $d/ is not world-searchable"
done
cmp -s "$b/config/corelata.example.yaml" "$here/../config/corelata.example.yaml" \
  || fail "config/corelata.example.yaml differs from deploy/config/"
# bytecode a local test run left next to the engine's pack is not part of the pack
diff -r -x __pycache__ -x '*.pyc' "$b/config/packs.example/icd203-base" \
  "$here/../../engine/corelata/standards/packs/icd203-base" >/dev/null \
  || fail "config/packs.example/icd203-base differs from the engine's built-in pack"
python3 - "$b" "$version" "$tar_file" <<'PY' || fail "owners, manifest, image tags or SBOMs (see above)"
import json, sys, tarfile
from pathlib import Path
b, version = Path(sys.argv[1]), sys.argv[2]
with tarfile.open(sys.argv[3]) as bundle:  # root-owned, so `sudo tar -xf` maps no local account
    for m in bundle:
        assert (m.uid, m.gid) == (0, 0) and m.uname in ("", "root") and m.gname in ("", "root"), (
            m.name, m.uid, m.gid, m.uname, m.gname)
manifest = json.loads((b / "manifest.json").read_text())
assert manifest["version"] == version, manifest["version"]
assert manifest["platform"] == "linux/amd64"
assert manifest["packs"] == ["icd203-base"], manifest["packs"]
expected = {"app.tar": f"corelata/app:{version}", "postgres.tar": "postgres:16-alpine"}
for archive, tag in expected.items():
    with tarfile.open(b / "images" / archive) as t:
        tags = [tag for entry in json.load(t.extractfile("manifest.json")) for tag in entry.get("RepoTags") or []]
    assert any(t in (tag, f"docker.io/library/{tag}") for t in tags), (archive, tags)
    assert any(i["file"] == f"images/{archive}" for i in manifest["images"]), archive
for sbom in (b / "sbom").glob("*.cdx.json"):
    assert json.loads(sbom.read_text())["bomFormat"] == "CycloneDX", sbom
PY
(cd "$b" && CORELATA_DB_PASSWORD=check docker compose --env-file /dev/null -f compose.yaml config -q) \
  || fail "compose.yaml does not resolve"
echo "ok: $(basename "$tar_file")"
