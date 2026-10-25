#!/bin/bash
# In-container build for lin64 and lin32 (images linux-x64, linux-x32: Ubuntu 14.04,
# g++-5, Qt 5.6.3 in /opt/qt56, cmake 3.10.0). Mirrors the TeamCity Linux builds.
#
# Contract (same for every platform, see common.build_command in ../common.py): source in /src (read-only),
# output in /out: build tree /out/build, install tree /out/install/MultiMC, logs
# /out/*.log. Settings, PLATFORM and BUILD_NUMBER come from the environment.

set -euo pipefail

# The checkout belongs to the host user; let CMake read its commit.
git config --global --add safe.directory "*"

# Incremental unless CLEAN=1. The install tree is always fresh.
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
    -DLauncher_TRANSLATIONS_BASE_URL="$TRANSLATIONS_BASE_URL" \
    -DLauncher_LAYOUT=lin-nodeps \
    -DLauncher_VERSION_BUILD="$BUILD_NUMBER" \
    -DLauncher_BUILD_PLATFORM="$PLATFORM" \
    -DLauncher_SUBREDDIT_URL="$SUBREDDIT_URL" \
    -DLauncher_DISCORD_URL="$DISCORD_URL" \
    -DLauncher_BUG_TRACKER_URL="$BUG_TRACKER_URL" \
    $CMAKE_EXTRA_ARGS \
    /src > /out/configure.log 2>&1 || { tail -40 /out/configure.log; exit 1; }

make -j"${JOBS:-$(nproc)}" > /out/build.log 2>&1 \
    || { grep -m30 -E "error|Error" /out/build.log; tail -20 /out/build.log; exit 1; }
make test > /out/test.log 2>&1 || { tail -30 /out/test.log; echo "TESTS FAILED"; exit 1; }
tail -3 /out/test.log
make install > /out/install.log 2>&1 || { tail -40 /out/install.log; exit 1; }
echo "INSTALL OK"
