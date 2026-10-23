#!/bin/bash
# In-container build for win32 (image windows-win32: GE-Proton10-15 and the old Win7 build
# VM's toolchain in $TOOLS: Qt 5.6.3 + MinGW 4.9.2, CMake 3.20.1, dumpbin, GnuWin32 zlib,
# OpenSSL 1.0, JDK 8u112). Mirrors the TeamCity Windows build, under Wine.
#
# Contract (same for every platform, see common.build_command in ../common.py): source in /src (read-only),
# output in /out: build tree /out/build, install tree /out/install/MultiMC, logs
# /out/*.log; the Wine prefix lives in /out/prefix. Settings, PLATFORM and BUILD_NUMBER
# come from the environment; TOOLS, WINE and PREFIX_TEMPLATE from the image.

set -euo pipefail

export WINEPREFIX=/out/prefix WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="

# Incremental unless CLEAN=1: the build tree and Wine prefix are kept. The install tree
# is always fresh.
rm -rf /out/install
if [ "$CLEAN" = 1 ]; then rm -rf "$WINEPREFIX" /out/build; fi
mkdir -p /out/build /out/install
if [ ! -d "$WINEPREFIX" ]; then
    cp -R "$PREFIX_TEMPLATE" "$WINEPREFIX"   # -R, not -a: the copy must belong to the running user
fi
# Only the drives we need: T: tools, S: source, O: output. Nothing else.
rm -f "$WINEPREFIX/dosdevices/z:" "$WINEPREFIX"/dosdevices/*::
ln -sfn "$TOOLS" "$WINEPREFIX/dosdevices/t:"
ln -sfn /src "$WINEPREFIX/dosdevices/s:"
ln -sfn /out "$WINEPREFIX/dosdevices/o:"

export WINEPATH='T:\Qt\Tools\mingw492_32\bin;T:\Qt\5.6.3\mingw49_32\bin;T:\Tools;T:\GnuWin32\bin;T:\jdk1.8.0_112\bin'
export JAVA_HOME='T:\jdk1.8.0_112'
CMAKE='T:\CMake-3.20.1\bin\cmake.exe'
QT='T:\Qt\5.6.3\mingw49_32'

cd /out/build
$WINE "$CMAKE" -G "MinGW Makefiles" \
    -DCMAKE_MAKE_PROGRAM=mingw32-make \
    -DCMAKE_C_COMPILER=gcc \
    -DCMAKE_CXX_COMPILER=g++ \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_INSTALL_PREFIX:PATH='O:\install\MultiMC' \
    -DCMAKE_PREFIX_PATH="$QT" \
    -DQt5_DIR="$QT" \
    -DZLIB_ROOT='T:\GnuWin32' \
    -DLauncher_NOTIFICATION_URL:STRING="$NOTIFICATION_URL" \
    -DLauncher_UPDATER_BASE="$UPDATER_BASE" \
    -DLauncher_LAYOUT=win-bundle \
    -DLauncher_VERSION_BUILD="$BUILD_NUMBER" \
    -DLauncher_BUILD_PLATFORM="$PLATFORM" \
    -DLauncher_SUBREDDIT_URL="$SUBREDDIT_URL" \
    -DLauncher_DISCORD_URL="$DISCORD_URL" \
    -DLauncher_BUG_TRACKER_URL="$BUG_TRACKER_URL" \
    -DCMAKE_GP_CMD_PATHS=T:/Tools \
    -DCMAKE_GP_TOOL=dumpbin \
    $CMAKE_EXTRA_ARGS \
    'S:\' > /out/configure.log 2>&1 || { tail -40 /out/configure.log; exit 1; }

$WINE "$CMAKE" --build . -- -j"${JOBS:-$(nproc)}" > /out/build.log 2>&1 \
    || { grep -m30 -E "error|Error" /out/build.log; tail -20 /out/build.log; exit 1; }
$WINE 'T:\CMake-3.20.1\bin\ctest.exe' > /out/test.log 2>&1 || { tail -30 /out/test.log; echo "TESTS FAILED"; exit 1; }
tail -3 /out/test.log
$WINE "$CMAKE" --install . > /out/install.log 2>&1 || { tail -40 /out/install.log; exit 1; }
cp "$TOOLS/OpenSSL-Win32/libeay32.dll" "$TOOLS/OpenSSL-Win32/ssleay32.dll" /out/install/MultiMC/
echo "INSTALL OK"
