#!/bin/bash
# Build the lin64 or lin32 Launcher in its toolchain image, mirroring the TeamCity Linux builds.
#
# Usage: build-linux.sh <lin64|lin32> <launcher-source-dir> <output-dir> [build-number]
#
# <launcher-source-dir> should be a git checkout on its branch (not detached), so the
# commit and branch get embedded like in the TeamCity builds.
# Settings (image, URLs, build type...) come from ../pipeline/defaults.env, a config file
# ($CONFIG) or the environment; see ../pipeline/config.sh.
# Images: lin64 = linux-x64 (Ubuntu 14.04, g++-5, Qt 5.6.3, cmake 3.10.0), lin32 = the same
# for i386 with cmake 3.10.0 built from source.

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/../pipeline/config.sh"
load_config

PLATFORM=$1
SRC=$(realpath "$2")
OUT=$(realpath -m "$3")
export BUILD_NUMBER=${4:-9999} PLATFORM

case "$PLATFORM" in
    lin64) IMAGE=$IMAGE_LIN64 ;;
    lin32) IMAGE=$IMAGE_LIN32 ;;
    *) echo "unknown platform $PLATFORM (lin64 or lin32)"; exit 2 ;;
esac

mkdir -p "$OUT"
# shellcheck disable=SC2046
docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$SRC:/src:ro" -v "$OUT:/out" \
    $(docker_env_args) -e BUILD_NUMBER -e PLATFORM \
    "$IMAGE" bash -euo pipefail -c '
# The checkout belongs to the host user; let CMake read its commit.
git config --global --add safe.directory "*"
# Incremental unless CLEAN=1: the build tree is kept between runs. It is mounted at the
# same path every time, so the paths cached by CMake stay valid. Install is always fresh.
rm -rf /out/install
if [ "$CLEAN" = 1 ]; then rm -rf /out/build; fi
mkdir -p /out/build && cd /out/build
cmake \
    -DCMAKE_C_COMPILER=/usr/bin/gcc-5 \
    -DCMAKE_CXX_COMPILER=/usr/bin/g++-5 \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_INSTALL_PREFIX:PATH=/out/install/MultiMC \
    -DCMAKE_PREFIX_PATH=/opt/qt56/ \
    -DQt5_DIR=/opt/qt56/ \
    -DLauncher_NOTIFICATION_URL:STRING="$NOTIFICATION_URL" \
    -DLauncher_UPDATER_BASE="$UPDATER_BASE" \
    -DLauncher_LAYOUT=lin-nodeps \
    -DLauncher_VERSION_BUILD="$BUILD_NUMBER" \
    -DLauncher_BUILD_PLATFORM="$PLATFORM" \
    -DLauncher_SUBREDDIT_URL="$SUBREDDIT_URL" \
    -DLauncher_DISCORD_URL="$DISCORD_URL" \
    -DLauncher_BUG_TRACKER_URL="$BUG_TRACKER_URL" \
    $CMAKE_EXTRA_ARGS \
    /src > /out/configure.log 2>&1 || { tail -40 /out/configure.log; exit 1; }
make -j"${JOBS:-$(nproc)}" > /out/build.log 2>&1 || { grep -m30 -E "error|Error" /out/build.log; tail -20 /out/build.log; exit 1; }
make test > /out/test.log 2>&1 || { tail -30 /out/test.log; echo "TESTS FAILED"; exit 1; }
tail -3 /out/test.log
make install > /out/install.log 2>&1 || { tail -40 /out/install.log; exit 1; }
echo "INSTALL OK"
'
