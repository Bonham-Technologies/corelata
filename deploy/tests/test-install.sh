#!/usr/bin/env bash
# Tests install.sh against a minimal fake bundle and a stub `docker` that records its calls.
# No images and no Docker daemon are needed. Usage: deploy/tests/test-install.sh
set -euo pipefail
deploy=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$work/bin"
cat >"$work/bin/sha256" <<'EOF'
#!/usr/bin/env bash
if command -v sha256sum >/dev/null; then exec sha256sum "$@"; else exec shasum -a 256 "$@"; fi
EOF
cat >"$work/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "$*" >>"$DOCKER_LOG"
if [ "$1 $2" = "compose version" ]; then echo "${STUB_COMPOSE_VERSION:-2.29.1}"; fi
EOF
chmod +x "$work/bin/docker" "$work/bin/sha256"
export PATH="$work/bin:$PATH"

new_bundle() {  # a fresh bundle directory, checksummed as bundle.sh does; prints its path
  local b
  b=$(mktemp -d "$work/bundle-XXXXXX")
  mkdir -p "$b/images" "$b/config/packs.example/icd203-base"
  cp "$deploy/install.sh" "$deploy/backup.sh" "$deploy/restore.sh" "$b/"
  echo app >"$b/images/app.tar"
  echo postgres >"$b/images/postgres.tar"
  echo "name: icd203-base" >"$b/config/packs.example/icd203-base/pack.yaml"
  cp "$deploy/config/corelata.example.yaml" "$deploy/config/corelata.demo.yaml" "$b/config/"
  cp "$deploy/compose.yaml" "$deploy/compose.demo.yaml" "$b/"
  echo "# operator guide" >"$b/operator-guide.md"
  echo '{}' >"$b/manifest.json"
  echo 0.0.0-test >"$b/VERSION"
  # shellcheck disable=SC2094  # find skips SHA256SUMS, so it is not read while written
  (cd "$b" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256 >SHA256SUMS)
  echo "$b"
}

install() {  # runs install.sh in bundle $1 with args; output in $work/out, docker calls in $work/log
  local b=$1; shift
  : >"$work/log"
  DOCKER_LOG="$work/log" "$b/install.sh" "$@" >"$work/out" 2>&1
}

# a fresh install loads every image and creates the config, the packs and .env
b=$(new_bundle)
install "$b" || fail "fresh install: $(cat "$work/out")"
{ grep -qx "load -i images/app.tar" "$work/log" && grep -qx "load -i images/postgres.tar" "$work/log"; } \
  || fail "fresh install: images not loaded: $(cat "$work/log")"
cmp -s "$b/config/corelata.yaml" "$b/config/corelata.example.yaml" || fail "config not created"
cmp -s "$b/config/packs/icd203-base/pack.yaml" "$b/config/packs.example/icd203-base/pack.yaml" \
  || fail "config/packs/icd203-base/pack.yaml not created"
grep -Eq '^CORELATA_DB_PASSWORD=[0-9a-f]{48}$' "$b/.env" || fail ".env has no 48-hex password"
[ "$(stat -c %a "$b/.env" 2>/dev/null || stat -f %Lp "$b/.env")" = 600 ] || fail ".env must be mode 600"
{ grep -q "config/corelata.yaml" "$work/out" && grep -q "docker compose up -d --wait" "$work/out"; } \
  || fail "the next steps are not printed"
grep -q "docker compose up -d --wait --force-recreate migrate api worker" "$work/out" \
  || fail "how to apply a config change is not printed"
echo "ok - a fresh install"

# a second run keeps the config, the edited pack and .env; none of them is checked against
# SHA256SUMS (an upgrade copies a new bundle over the install, then runs install.sh)
echo "# edited" >>"$b/config/corelata.yaml"
echo "# tuned" >>"$b/config/packs/icd203-base/pack.yaml"
cp "$b/config/corelata.yaml" "$work/config.before"
cp "$b/config/packs/icd203-base/pack.yaml" "$work/pack.before"
cp "$b/.env" "$work/env.before"
install "$b" || fail "second run: $(cat "$work/out")"
cmp -s "$b/config/corelata.yaml" "$work/config.before" || fail "second run changed the config"
cmp -s "$b/config/packs/icd203-base/pack.yaml" "$work/pack.before" || fail "second run changed the pack"
cmp -s "$b/.env" "$work/env.before" || fail "second run changed .env"
echo "ok - a second run keeps the config, the packs and .env"

# a damaged or incomplete bundle is refused before anything is loaded
b=$(new_bundle)
echo x >>"$b/images/postgres.tar"
if install "$b"; then fail "a damaged bundle was installed"; fi
grep -q "^error: the bundle is damaged or incomplete (.*images/postgres.tar" "$work/out" \
  || fail "damaged: $(cat "$work/out")"
if grep -q "^load" "$work/log"; then fail "damaged: an image was loaded"; fi
[ ! -e "$b/.env" ] || fail "damaged: .env was created"
echo "ok - a damaged bundle is refused"

b=$(new_bundle)
rm "$b/images/app.tar"
if install "$b"; then fail "an incomplete bundle was installed"; fi
grep -q "^error: the bundle is damaged or incomplete (.*images/app.tar" "$work/out" \
  || fail "incomplete: $(cat "$work/out")"
if grep -q "^load" "$work/log"; then fail "incomplete: an image was loaded"; fi
[ ! -e "$b/.env" ] || fail "incomplete: .env was created"
echo "ok - an incomplete bundle is refused"

b=$(new_bundle)
rm "$b/SHA256SUMS"
if install "$b"; then fail "a bundle without SHA256SUMS was installed"; fi
grep -q "^error: SHA256SUMS is missing" "$work/out" || fail "no SHA256SUMS: $(cat "$work/out")"
if grep -q "^load" "$work/log"; then fail "no SHA256SUMS: an image was loaded"; fi
[ ! -e "$b/.env" ] || fail "no SHA256SUMS: .env was created"
echo "ok - a bundle without checksums is refused"

b=$(new_bundle)
if STUB_COMPOSE_VERSION=2.20.3 install "$b"; then fail "an old Compose was accepted"; fi
grep -q "^error: Docker Compose 2.20.3 is too old; Corelata needs 2.24.0 or newer" "$work/out" \
  || fail "old compose: $(cat "$work/out")"
STUB_COMPOSE_VERSION=v5.1.3 install "$b" || fail "Compose v5.1.3 was refused: $(cat "$work/out")"
echo "ok - the Compose version is checked"

# an interrupted install (config, no .env) is completed without touching the config
b=$(new_bundle)
cp "$b/config/corelata.example.yaml" "$b/config/corelata.yaml"
echo "# mine" >>"$b/config/corelata.yaml"
cp "$b/config/corelata.yaml" "$work/config.before"
install "$b" || fail "interrupted: $(cat "$work/out")"
cmp -s "$b/config/corelata.yaml" "$work/config.before" || fail "interrupted: config changed"
grep -Eq '^CORELATA_DB_PASSWORD=[0-9a-f]{48}$' "$b/.env" || fail "interrupted: no .env"
echo "ok - an interrupted install keeps the config and creates .env"

# a hardened host's umask 077 must not leave the config unreadable by the containers' uid 10001
b=$(new_bundle)
(umask 077 && install "$b") || fail "umask 077: $(cat "$work/out")"
[ "$(find "$b/config" ! -perm -o=r)" = "" ] || fail "umask 077: a file under config/ is not world-readable"
[ "$(find "$b/config" -type d ! -perm -o=x)" = "" ] || fail "umask 077: a directory under config/ is not world-searchable"
[ -f "$b/config/packs/icd203-base/pack.yaml" ] || fail "umask 077: the pack was not copied"
[ "$(stat -c %a "$b/.env" 2>/dev/null || stat -f %Lp "$b/.env")" = 600 ] || fail "umask 077: .env must stay mode 600"
echo "ok - under umask 077 the config stays readable by the containers"

b=$(new_bundle)
(cd / && "$b/install.sh" --help) >"$work/out" 2>&1 || fail "--help failed: $(cat "$work/out")"
grep -q "Usage: ./install.sh" "$work/out" || fail "--help text: $(cat "$work/out")"
echo "ok - --help works from any directory"

b=$(new_bundle)
if install "$b" --bogus; then fail "an unknown option was accepted"; fi
grep -q "^error: unknown option --bogus" "$work/out" || fail "usage: $(cat "$work/out")"
echo "ok - unknown options are refused"

echo "install.sh: all tests passed"
