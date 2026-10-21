#!/bin/bash
# Build one platform in its toolchain container. The same for every platform.
#
# Usage: run-build.sh <platform> <launcher-source-dir> <output-dir> [build-number]
#
#   platform     lin64, lin32, win32 or osx64-5.15.2
#   source dir   a git checkout on its branch (not detached), with submodules, so the
#                commit and branch get embedded like in the TeamCity builds
#   output dir   gets build/ (kept between runs unless CLEAN=1), install/, *.log
#
# Every container is run the same way: no network, as the calling user, source at /src
# (read-only), output at /out, the build steps (build/<script>.sh) at /build (read-only),
# all settings (defaults.env, $CONFIG, environment) plus PLATFORM and BUILD_NUMBER in the
# environment. The images contain only toolchains.

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/config.sh"
load_config

export PLATFORM=$1
SRC=$(realpath "$2")
OUT=$(realpath -m "$3")
export BUILD_NUMBER=${4:-9999}

case "$PLATFORM" in
    lin64)        IMAGE=$IMAGE_LIN64 SCRIPT=linux.sh ;;
    lin32)        IMAGE=$IMAGE_LIN32 SCRIPT=linux.sh ;;
    win32)        IMAGE=$IMAGE_WIN32 SCRIPT=win32.sh ;;
    osx64-5.15.2) IMAGE=$IMAGE_OSX64 SCRIPT=osx64.sh ;;
    *) echo "unknown platform $PLATFORM" >&2; exit 2 ;;
esac

mkdir -p "$OUT"
# shellcheck disable=SC2046
exec docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$SRC:/src:ro" -v "$OUT:/out" -v "$HERE/build:/build:ro" \
    $(docker_env_args) -e PLATFORM -e BUILD_NUMBER \
    "$IMAGE" bash "/build/$SCRIPT"
