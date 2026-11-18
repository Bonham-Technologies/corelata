#!/usr/bin/env bash
# Build the offline bundle (spec §12) on a machine with Docker and internet access.
#   deploy/bundle.sh                      -> dist/corelata-<version>-linux-amd64.tar (+ .sha256)
# Options: --version V (default: the tag at HEAD, else <corelata version>-g<sha>), --out DIR
# (default: dist), --allow-dirty, --keep-stage (keep the unpacked directory next to the tarball).
# OCR_LANGUAGES="eng fra" picks the Tesseract language packs in the image (default: eng; operator
# guide, "Scanned PDFs").
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
die() { echo "error: $*" >&2; exit 1; }
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

PLATFORM=${PLATFORM:-linux/amd64}
# The tarball name, manifest and check-bundle.sh all say linux/amd64 (the air-gapped hosts).
[ "$PLATFORM" = linux/amd64 ] || die "PLATFORM=$PLATFORM is not supported; the bundle is linux/amd64 only"
POSTGRES_IMAGE=postgres:16-alpine
OCR_LANGUAGES=${OCR_LANGUAGES:-eng}
[[ "$OCR_LANGUAGES" =~ ^[A-Za-z0-9_\ ]+$ ]] || die "OCR_LANGUAGES='$OCR_LANGUAGES': give Tesseract codes separated by spaces, such as \"eng fra\""
SYFT_IMAGE=anchore/syft:v1.18.1

version="" out="$repo/dist" allow_dirty=false keep=false
while [ $# -gt 0 ]; do
  case $1 in
    --version) version=${2:?--version needs a value}; shift ;;
    --out) out=${2:?--out needs a directory}; shift ;;
    --allow-dirty) allow_dirty=true ;;
    --keep-stage) keep=true ;;
    *) die "unknown option $1 (see the comment at the top of deploy/bundle.sh)" ;;
  esac
  shift
done
if ! $allow_dirty && [ -n "$(git -C "$repo" status --porcelain)" ]; then
  die "the working tree has uncommitted changes; commit them or pass --allow-dirty"
fi
if [ -z "$version" ]; then
  if tag=$(git -C "$repo" describe --tags --exact-match 2>/dev/null); then
    version=${tag#v}
  else
    base=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$repo/engine/corelata/__init__.py")
    version="$base-g$(git -C "$repo" rev-parse --short HEAD)"
  fi
fi

name="corelata-$version"
mkdir -p "$out"
out=$(cd "$out" && pwd)
stage="$out/$name"
rm -rf "$stage"
mkdir -p "$stage/images" "$stage/config" "$stage/sbom" "$stage/examples"
app="corelata/app:$version"

echo "== image ($PLATFORM)"
# --provenance=false: buildx's provenance attestation turns `docker save` into a multi-manifest
# tar and confuses `docker image inspect` ids.
docker build --provenance=false --platform "$PLATFORM" -f "$repo/deploy/docker/app.Dockerfile" \
  --build-arg VERSION="$version" --build-arg OCR_LANGUAGES="$OCR_LANGUAGES" -t "$app" "$repo"
"$repo/deploy/tests/check-app-image.sh" "$app"
docker pull --platform "$PLATFORM" "$POSTGRES_IMAGE"
docker save -o "$stage/images/app.tar" "$app"
docker save -o "$stage/images/postgres.tar" "$POSTGRES_IMAGE"

echo "== files"
for f in compose.yaml compose.demo.yaml; do
  sed "s/\${CORELATA_VERSION:-dev}/$version/g" "$repo/deploy/$f" >"$stage/$f"
done
cp "$repo/deploy/config/corelata.example.yaml" "$repo/deploy/config/corelata.demo.yaml" "$stage/config/"
# install.sh copies it to config/packs once: the operator's edited packs are not in SHA256SUMS
mkdir -p "$stage/config/packs.example"
cp -R "$repo/engine/corelata/standards/packs/icd203-base" "$stage/config/packs.example/"
find "$stage/config/packs.example" -name '__pycache__' -prune -exec rm -rf {} +
cp "$repo/docs/examples/"* "$stage/examples/"
cp "$repo/deploy/install.sh" "$repo/deploy/backup.sh" "$repo/deploy/restore.sh" "$stage/"
chmod 755 "$stage"/*.sh
cp "$repo/docs/operator-guide.md" "$stage/operator-guide.md"
echo "$version" >"$stage/VERSION"
chmod -R a+rX "$stage/config" "$stage/examples" # the containers run as uid 10001

echo "== SBOMs (CycloneDX)"
# syft runs as the caller (so the SBOMs are theirs) and unpacks every layer into /tmp, which is
# a disk-backed directory under --out, not a tmpfs (RAM).
scratch=$(mktemp -d "$out/.syft-tmp.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
syft=(docker run --rm --user "$(id -u):$(id -g)" -v "$scratch:/tmp" -e HOME=/tmp -e XDG_CACHE_HOME=/tmp
  -v "$stage/sbom:/sbom")
# sbom NAME SOURCE MOUNT [SYFT-ARG...]: no -q, which would hide syft's errors; an empty file is an error too
sbom() {
  local name=$1 source=$2 mount=$3
  shift 3
  if ! "${syft[@]}" -v "$mount" "$SYFT_IMAGE" "$source" "$@" -o "cyclonedx-json=/sbom/$name.cdx.json"; then
    die "the SBOM for $name failed; see the message above"
  fi
  if [ ! -s "$stage/sbom/$name.cdx.json" ]; then
    die "the SBOM for $name is empty; see the message above"
  fi
}
for image in app postgres; do
  sbom "$image" "docker-archive:/images/$image.tar" "$stage/images:/images:ro"
done
sbom web dir:/src "$repo/web:/src:ro" --exclude './node_modules/**'

echo "== manifest and checksums"
python3 - "$stage" "$version" "$(git -C "$repo" rev-parse HEAD)" "$PLATFORM" "$app" "$POSTGRES_IMAGE" <<'PY'
import datetime, json, subprocess, sys
from pathlib import Path
stage, version, commit, platform, *images = sys.argv[1:]
def inspect(image):
    out = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)[0]
    return {"id": info["Id"], "repo_digests": info.get("RepoDigests") or []}
files = ["images/app.tar", "images/postgres.tar"]
manifest = {
    "version": version, "commit": commit, "platform": platform,
    "built_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    "images": [{"file": f, "tag": i, **inspect(i)} for f, i in zip(files, images)],
    "packs": sorted(p.name for p in Path(stage, "config", "packs.example").iterdir() if p.is_dir()),
}
Path(stage, "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
(cd "$stage" && find . -type f -print0 | sort -z | xargs -0 bash -c \
  'if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi' _ >"$out/SHA256SUMS.$$")
mv "$out/SHA256SUMS.$$" "$stage/SHA256SUMS"

echo "== tarball"
tarball="$name-linux-amd64.tar"
# Every member is owned by root (uid and gid 0, no names): `sudo tar -xf` keeps the archive's
# owners, and the builder's uid may be some other account on the target host.
if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  owner=(--owner=0 --group=0 --numeric-owner)
else # bsdtar (macOS)
  owner=(--uid 0 --gid 0 --numeric-owner)
fi
(cd "$out" && COPYFILE_DISABLE=1 tar "${owner[@]}" -cf "$tarball" "$name" && sha256 "$tarball" >"$tarball.sha256")
$keep || rm -rf "$stage"
echo "Built $out/$tarball ($(du -h "$out/$tarball" | cut -f1))"
