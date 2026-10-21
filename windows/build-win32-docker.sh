#!/bin/bash
# Build the win32 Launcher in the multimc/toolchains/windows-win32 image.
# Usage: build-win32-docker.sh <launcher-source-dir> <output-dir> [build-number]
# <launcher-source-dir> should be a git checkout on its branch (not detached), so the
# commit and branch get embedded like in the TeamCity builds.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/../pipeline/config.sh"
load_config
SRC=$(realpath "$1")
OUT=$(realpath -m "$2")
mkdir -p "$OUT"
# shellcheck disable=SC2046
docker run --rm --network none -u "$(id -u):$(id -g)" \
    -v "$SRC:/src:ro" -v "$OUT:/out" $(docker_env_args) \
    "$IMAGE_WIN32" /src /out "${3:-9999}"
