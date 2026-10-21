#!/bin/bash
# Cross-build the osx64-5.15.2 Launcher on Linux, mirroring the TeamCity macOS build.
#
# Usage: build-osx64.sh <launcher-source-dir> <output-dir> [build-number]
#
# <launcher-source-dir> should be a clean git checkout with submodules, so the
# commit gets embedded in the binary like in the TeamCity builds.
# SOURCE_DATE_EPOCH is fixed (see below): Qt 5.15's rcc embeds file modification times.
#
# Needs the multimc/toolchains/macos-cross image, which contains everything including the
# macmini Qt 5.15.2 (with Linux moc/rcc/uic and a qmake stand-in, see README.md).
# Settings (image, URLs, deployment target...) come from ../../pipeline/defaults.env, a
# config file ($CONFIG) or the environment; see ../../pipeline/config.sh.

set -euo pipefail

SRC=$(realpath "$1")
OUT=$(realpath -m "$2")
export BUILD_NUMBER=${3:-9999}
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/../../pipeline/config.sh"
load_config
export QT=/Users/peterix/Qt/5.15.2/clang_64
# Qt 5.15's rcc embeds file modification times in resources. A fixed value (1980-01-01, the
# zip epoch) makes the binary independent of when the checkout was made, and makes clean and
# incremental builds agree (with the commit time, unchanged resources would keep an older
# commit's time in an incremental build).
export SOURCE_DATE_EPOCH=315532800

mkdir -p "$OUT"
# shellcheck disable=SC2046
docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$SRC:/src:ro" \
    -v "$OUT:/out" \
    -v "$HERE:/cross:ro" \
    $(docker_env_args) -e BUILD_NUMBER -e QT -e SOURCE_DATE_EPOCH \
    "$IMAGE_OSX64" bash -euo pipefail -c '
eval "$(/opt/osxcross/bin/osxcross-conf)"
TRIPLE=x86_64-apple-$OSXCROSS_TARGET
export OSXCROSS_HOST=$TRIPLE OSXCROSS_TARGET_DIR OSXCROSS_TARGET OSXCROSS_SDK
export OSXCROSS_C_COMPILER=clang OSXCROSS_CXX_COMPILER=clang++
# BundleUtilities calls otool/install_name_tool by their plain names.
mkdir -p /tmp/tools
for t in otool install_name_tool lipo codesign_allocate; do
    ln -sf /opt/osxcross/bin/$TRIPLE-$t /tmp/tools/$t
done
export PATH=/tmp/tools:$PATH
# The source is a git checkout owned by the host user; let CMake read its commit.
git config --global --add safe.directory "*"

# Incremental unless CLEAN=1: the build tree is kept between runs. It is mounted at the
# same path every time, so the paths cached by CMake stay valid. Install is always fresh.
if [ "$CLEAN" = 1 ]; then rm -rf /out/build; fi
mkdir -p /out/build && cd /out/build
cmake \
    -DCMAKE_TOOLCHAIN_FILE=/cross/toolchain-osx64.cmake \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_OSX_DEPLOYMENT_TARGET="$OSX_DEPLOYMENT_TARGET" \
    -DCMAKE_INSTALL_PREFIX:PATH=/out/install \
    -DCMAKE_PREFIX_PATH="$QT" \
    -DQt5_DIR="$QT/lib/cmake/Qt5" \
    -DLauncher_LAYOUT=mac-bundle \
    -DLauncher_VERSION_BUILD="$BUILD_NUMBER" \
    -DLauncher_BUILD_PLATFORM=osx64-5.15.2 \
    -DLauncher_NOTIFICATION_URL:STRING="$NOTIFICATION_URL" \
    -DLauncher_UPDATER_BASE="$UPDATER_BASE" \
    -DLauncher_SUBREDDIT_URL="$SUBREDDIT_URL" \
    -DLauncher_DISCORD_URL="$DISCORD_URL" \
    -DLauncher_BUG_TRACKER_URL="$BUG_TRACKER_URL" \
    -DCMAKE_GP_TOOL=otool \
    $CMAKE_EXTRA_ARGS \
    /src > /out/configure.log 2>&1 || { tail -40 /out/configure.log; exit 1; }
make -j"${JOBS:-$(nproc)}" > /out/build.log 2>&1 || { grep -m30 -E "error|Error" /out/build.log; tail -20 /out/build.log; exit 1; }
rm -rf /out/install
# Install scripts run in CMake script mode, where APPLE is unset on a Linux host.
cmake -DAPPLE=1 -DCMAKE_INSTALL_PREFIX=/out/install -P cmake_install.cmake > /out/install.log 2>&1 \
    || { tail -40 /out/install.log; exit 1; }
# Same artifact as the TeamCity build: package.tar.gz with MultiMC.app at its root.
cmake -E chdir /out/install cmake -E tar cfz /out/package.tar.gz MultiMC.app
echo "INSTALL OK"
'
