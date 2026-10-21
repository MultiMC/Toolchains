#!/bin/bash
# Build, package and verify a Launcher release for all platforms. Deploys nothing.
#
# Usage: release-build.sh [--config FILE] [--incremental [--clean]] <build-number> <out-dir> [commit]
#
#   --config      settings file overriding defaults.env (environment overrides both)
#   --incremental reuse a persistent source checkout and per-platform build trees in
#                 $STATE/work (for development). The checkout is updated with git, so only
#                 changed files get new timestamps; CMake configure runs every time.
#   --clean       with --incremental: start the persistent build trees from scratch
#   build-number  Launcher_VERSION_BUILD; must keep increasing for the updater
#   out-dir       new, empty directory for this release
#   commit        a commit on $LAUNCHER_BRANCH (default: its current head)
#
# Steps: update the local Launcher mirror ($STATE, default ./state), check out the branch
# (as a branch, so the commit and refs/heads/<branch> get embedded) at the commit, build
# $PLATFORMS in parallel in their toolchain containers (run-build.sh), package them like TeamCity's
# deploy did, run compat-check.py against $BASELINES, write manifest.json.
# Exit status 0 only if every build and every compatibility check passed.

set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/config.sh"
CONFIG_FILE= INCREMENTAL= FORCE_CLEAN=
while [ "${1:-}" != "${1#--}" ]; do
    case "$1" in
        --config) CONFIG_FILE=$(realpath "$2"); shift 2 ;;
        --incremental) INCREMENTAL=1; shift ;;
        --clean) FORCE_CLEAN=1; shift ;;
        *) echo "unknown option $1"; exit 2 ;;
    esac
done
load_config "$CONFIG_FILE"
export CONFIG=$CONFIG_FILE   # the platform scripts load the same settings

BUILD_NUMBER=$1
OUT=$(realpath -m "$2")
COMMIT=${3:-}
STATE=${STATE:-$HERE/state}
BRANCH=$LAUNCHER_BRANCH

[[ "$BUILD_NUMBER" =~ ^[0-9]+$ ]] || { echo "build number must be a number"; exit 2; }
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT")" ]; then echo "$OUT is not empty"; exit 2; fi
mkdir -p "$OUT" "$STATE"
log() { echo "[$(date +%T)] $*"; }

if [ -n "$INCREMENTAL" ]; then
    WORK=$STATE/work
    mkdir -p "$WORK"
    exec 9> "$WORK/.lock"
    flock -n 9 || { echo "another incremental build is using $WORK"; exit 2; }
    SRC_DIR=$WORK/src BUILD_ROOT=$WORK/build
    if [ -n "$FORCE_CLEAN" ]; then export CLEAN=1; else export CLEAN=0; fi
else
    [ -z "$FORCE_CLEAN" ] || { echo "--clean only makes sense with --incremental"; exit 2; }
    SRC_DIR=$OUT/src BUILD_ROOT=$OUT/build
    export CLEAN=1
fi

# --- source --------------------------------------------------------------------------
if [ ! -d "$STATE/launcher.git" ]; then
    log "cloning mirror of $LAUNCHER_REPO"
    git clone -q --mirror "$LAUNCHER_REPO" "$STATE/launcher.git"
fi
log "updating mirror"
git -C "$STATE/launcher.git" fetch -q --prune origin
COMMIT=$(git -C "$STATE/launcher.git" rev-parse --verify "${COMMIT:-refs/heads/$BRANCH}^{commit}")
git -C "$STATE/launcher.git" merge-base --is-ancestor "$COMMIT" "refs/heads/$BRANCH" \
    || { echo "$COMMIT is not on $BRANCH"; exit 2; }

log "checking out $BRANCH at $COMMIT${INCREMENTAL:+ (incremental, CLEAN=$CLEAN)}"
if [ ! -d "$SRC_DIR/.git" ]; then
    git clone -q --no-hardlinks -b "$BRANCH" "$STATE/launcher.git" "$SRC_DIR"
else
    # Persistent checkout: only files that actually change get touched (and new mtimes).
    git -C "$SRC_DIR" fetch -q origin
    git -C "$SRC_DIR" checkout -q -B "$BRANCH" "$COMMIT"
fi
git -C "$SRC_DIR" reset -q --hard "$COMMIT"
git -C "$SRC_DIR" clean -q -ffdx
git -C "$SRC_DIR" submodule -q sync --recursive
git -C "$SRC_DIR" submodule -q update --init --recursive
git -C "$SRC_DIR" submodule -q foreach --recursive git clean -q -ffdx

# --- build ---------------------------------------------------------------------------
build() {
    "$HERE/run-build.sh" "$1" "$SRC_DIR" "$BUILD_ROOT/$1" "$BUILD_NUMBER"
}

log "building $PLATFORMS"
declare -A PIDS
for p in $PLATFORMS; do
    build "$p" > "$OUT/build-$p.log" 2>&1 &
    PIDS[$p]=$!
done
FAILED=""
for p in $PLATFORMS; do
    if wait "${PIDS[$p]}"; then log "  $p: built"; else log "  $p: BUILD FAILED (see build-$p.log)"; FAILED="$FAILED $p"; fi
done
[ -z "$FAILED" ] || { log "build failed:$FAILED"; exit 1; }

# --- package -------------------------------------------------------------------------
mkdir -p "$OUT/packages"
for p in $PLATFORMS; do
    case "$p" in
        win32) (cd "$BUILD_ROOT/$p/install" && python3 -I -m zipfile -c "$OUT/packages/mmc-$BRANCH-$p.zip" MultiMC) ;;
        osx64-5.15.2) tar -C "$BUILD_ROOT/$p/install" -czf "$OUT/packages/mmc-$BRANCH-$p.tar.gz" MultiMC.app ;;
        *) tar -C "$BUILD_ROOT/$p/install" -czf "$OUT/packages/mmc-$BRANCH-$p.tar.gz" MultiMC ;;
    esac
done

# --- compatibility gate --------------------------------------------------------------
log "compatibility checks against $(basename "$BASELINES")"
GATE_FAILED=""
for p in $PLATFORMS; do
    case "$p" in
        win32) tree="$BUILD_ROOT/$p/install/MultiMC"; base="$BASELINES/mmc-develop-$p.zip" ;;
        osx64-5.15.2) tree="$BUILD_ROOT/$p/install/MultiMC.app"; base="$BASELINES/mmc-develop-$p.tar.gz" ;;
        *) tree="$BUILD_ROOT/$p/install/MultiMC"; base="$BASELINES/mmc-develop-$p.tar.gz" ;;
    esac
    python3 -I "$HERE/compat-check.py" "$p" "$tree" "$base" --json "$OUT/compat-$p.json" > "$OUT/compat-$p.txt" || GATE_FAILED="$GATE_FAILED $p"
    sed 's/^/    /' "$OUT/compat-$p.txt"
done

# --- manifest ------------------------------------------------------------------------
python3 -I - "$OUT" "$COMMIT" "$BUILD_NUMBER" "$PLATFORMS" "$BRANCH" "$BUILD_ROOT" "${INCREMENTAL:+incremental}" <<'EOF'
import hashlib, json, os, sys, time
out, commit, build, platforms, branch, build_root, mode = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4].split(), sys.argv[5], sys.argv[6], sys.argv[7] or "clean"
manifest = {"commit": commit, "branch": branch, "build_number": build, "mode": mode,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "platforms": {}}
for p in platforms:
    pkg = [f for f in os.listdir(os.path.join(out, "packages")) if f.startswith("mmc-%s-%s." % (branch, p))][0]
    data = open(os.path.join(out, "packages", pkg), "rb").read()
    gate = json.load(open(os.path.join(out, "compat-%s.json" % p)))
    manifest["platforms"][p] = {"package": pkg, "sha256": hashlib.sha256(data).hexdigest(),
                                "size": len(data), "install_tree": os.path.join(build_root, p, "install"),
                                "compat_passed": gate["passed"], "compat_problems": gate["problems"]}
manifest["releasable"] = all(v["compat_passed"] for v in manifest["platforms"].values())
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=2, sort_keys=True)
EOF

if [ -n "$GATE_FAILED" ]; then
    log "NOT RELEASABLE: compatibility check failed for$GATE_FAILED"
    exit 1
fi
log "releasable: build $BUILD_NUMBER of $COMMIT, see $OUT/manifest.json"
