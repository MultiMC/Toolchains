#!/bin/bash
# Cross-build the osx64-5.15.2 Launcher on Linux, mirroring the TeamCity macOS build.
#
# Usage: build-osx64.sh <launcher-source-dir> <output-dir> [build-number]
#
# <launcher-source-dir> should be a clean git checkout with submodules, so the
# commit gets embedded in the binary like in the TeamCity builds.
#
# Needs the multimc/toolchains/macos-cross image and work/qt (the macmini Qt 5.15.2
# with Linux moc/rcc/uic and a qmake stand-in, see README.md).

set -euo pipefail

SRC=$(realpath "$1")
OUT=$(realpath -m "$2")
BUILD_NUMBER=${3:-9999}
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
IMAGE=${IMAGE:-multimc/toolchains/macos-cross:dev}
QT=/Users/peterix/Qt/5.15.2/clang_64

mkdir -p "$OUT"
docker run --rm --network none \
    -v "$SRC:/src:ro" \
    -v "$OUT:/out" \
    -v "$HERE:/cross:ro" \
    -v "$HERE/work/qt/Users/peterix/Qt/5.15.2:/Users/peterix/Qt/5.15.2:ro" \
    -e BUILD_NUMBER="$BUILD_NUMBER" -e QT="$QT" \
    "$IMAGE" bash -euo pipefail -c '
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

mkdir -p /tmp/build && cd /tmp/build
cmake \
    -DCMAKE_TOOLCHAIN_FILE=/cross/toolchain-osx64.cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=10.13 \
    -DCMAKE_INSTALL_PREFIX:PATH=/out/install \
    -DCMAKE_PREFIX_PATH="$QT" \
    -DQt5_DIR="$QT/lib/cmake/Qt5" \
    -DLauncher_LAYOUT=mac-bundle \
    -DLauncher_VERSION_BUILD=$BUILD_NUMBER \
    -DLauncher_BUILD_PLATFORM=osx64-5.15.2 \
    -DCMAKE_GP_TOOL=otool \
    /src > /out/configure.log 2>&1 || { tail -40 /out/configure.log; exit 1; }
make -j$(nproc) > /out/build.log 2>&1 || { grep -m30 -E "error|Error" /out/build.log; tail -20 /out/build.log; exit 1; }
rm -rf /out/install
# Install scripts run in CMake script mode, where APPLE is unset on a Linux host.
cmake -DAPPLE=1 -DCMAKE_INSTALL_PREFIX=/out/install -P cmake_install.cmake > /out/install.log 2>&1 \
    || { tail -40 /out/install.log; exit 1; }
# Same artifact as the TeamCity build: package.tar.gz with MultiMC.app at its root.
cmake -E chdir /out/install cmake -E tar cfz /out/package.tar.gz MultiMC.app
echo "INSTALL OK"
'
