#!/bin/bash
# In-container build for osx64-5.15.2 (image macos-osx64: osxcross + SDK 11.1, the macmini
# Qt 5.15.2 with Linux moc/rcc/uic, JDK 8). Mirrors the TeamCity macOS build, cross-built.
#
# Contract (same for every platform, see common.build_command in ../common.py): source in /src (read-only),
# output in /out: build tree /out/build, install tree /out/install/MultiMC.app, logs
# /out/*.log. Settings, PLATFORM and BUILD_NUMBER come from the environment.
# No unit tests: they are macOS binaries.

set -euo pipefail

QT=/Users/peterix/Qt/5.15.2/clang_64
# Qt 5.15's rcc embeds file modification times in resources. A fixed value (1980-01-01, the
# zip epoch) makes the result independent of the checkout and makes clean and incremental
# builds agree.
export SOURCE_DATE_EPOCH=315532800

eval "$(/opt/osxcross/bin/osxcross-conf)"
TRIPLE=x86_64-apple-$OSXCROSS_TARGET
export OSXCROSS_HOST=$TRIPLE OSXCROSS_TARGET_DIR OSXCROSS_TARGET OSXCROSS_SDK
export OSXCROSS_C_COMPILER=clang OSXCROSS_CXX_COMPILER=clang++
# BundleUtilities calls otool/install_name_tool by their plain names.
mkdir -p /tmp/tools
for t in otool install_name_tool lipo codesign_allocate; do
    ln -sf "/opt/osxcross/bin/$TRIPLE-$t" "/tmp/tools/$t"
done
export PATH=/tmp/tools:$PATH
# The checkout belongs to the host user; let CMake read its commit.
git config --global --add safe.directory "*"

# Incremental unless CLEAN=1. The install tree is always fresh.
rm -rf /out/install
if [ "$CLEAN" = 1 ]; then rm -rf /out/build; fi
mkdir -p /out/build && cd /out/build

cmake \
    -DCMAKE_TOOLCHAIN_FILE=/opt/toolchain-osx64.cmake \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_OSX_DEPLOYMENT_TARGET="$OSX_DEPLOYMENT_TARGET" \
    -DCMAKE_INSTALL_PREFIX:PATH=/out/install \
    -DCMAKE_PREFIX_PATH="$QT" \
    -DQt5_DIR="$QT/lib/cmake/Qt5" \
    -DLauncher_LAYOUT=mac-bundle \
    -DLauncher_VERSION_BUILD="$BUILD_NUMBER" \
    -DLauncher_BUILD_PLATFORM="$PLATFORM" \
    -DLauncher_NOTIFICATION_URL:STRING="$NOTIFICATION_URL" \
    -DLauncher_UPDATER_BASE="$UPDATER_BASE" \
    -DLauncher_SUBREDDIT_URL="$SUBREDDIT_URL" \
    -DLauncher_DISCORD_URL="$DISCORD_URL" \
    -DLauncher_BUG_TRACKER_URL="$BUG_TRACKER_URL" \
    -DCMAKE_GP_TOOL=otool \
    $CMAKE_EXTRA_ARGS \
    /src > /out/configure.log 2>&1 || { tail -40 /out/configure.log; exit 1; }

make -j"${JOBS:-$(nproc)}" > /out/build.log 2>&1 \
    || { grep -m30 -E "error|Error" /out/build.log; tail -20 /out/build.log; exit 1; }
# Install scripts run in CMake script mode, where APPLE is unset on a Linux host.
cmake -DAPPLE=1 -DCMAKE_INSTALL_PREFIX=/out/install -P cmake_install.cmake > /out/install.log 2>&1 \
    || { tail -40 /out/install.log; exit 1; }
echo "INSTALL OK"
