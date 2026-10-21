#!/bin/bash
# Build the win32 Launcher under Wine, mirroring the TeamCity Windows build (Win7 VM).
#
# Usage: build-win32.sh <launcher-source-dir> <output-dir> [build-number]
#
# Toolchain = the VM's, from Tools/ (mapped as T:): Qt 5.6.3 + MinGW 4.9.2 (Tools/Qt),
# CMake 3.20.1 (Tools/CMake-3.20.1, from the VM image), dumpbin for bundling (Tools/Tools),
# zlib from GnuWin32, OpenSSL 1.0 DLLs from Tools/OpenSSL-Win32, JDK 8u112.
# A fresh Wine prefix is created in <output-dir>/prefix for every build (copied from
# $PREFIX_TEMPLATE when set, as in the Docker image, otherwise made with wineboot).
#
# Runs on a host with Wine and Tools/ next to this script, or inside the
# multimc/toolchains/windows image (see Dockerfile, build-win32-docker.sh).

set -euo pipefail

SRC=$(realpath "$1")
OUT=$(realpath -m "$2")
BUILD_NUMBER=${3:-9999}
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Settings: on a host, from ../pipeline (defaults.env, $CONFIG, environment); in the image,
# build-win32-docker.sh passes them in through the environment.
if [ -f "$HERE/../pipeline/config.sh" ]; then
    source "$HERE/../pipeline/config.sh"
    load_config
fi
: "${BUILD_TYPE:?}" "${NOTIFICATION_URL:?}" "${UPDATER_BASE:?}" "${SUBREDDIT_URL:?}" "${DISCORD_URL:?}" "${BUG_TRACKER_URL:?}"
TOOLS=${TOOLS:-$HERE/Tools}
WINE=${WINE:-wine}

export WINEPREFIX="$OUT/prefix"
export WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="

# Incremental unless CLEAN=1: the build tree and Wine prefix are kept between runs (O: and
# S: are the same every time, so CMake's cached paths stay valid). The install tree is
# always fresh.
mkdir -p "$OUT"
rm -rf "$OUT/install"
if [ "${CLEAN:-1}" = 1 ]; then rm -rf "$WINEPREFIX" "$OUT/build"; fi
mkdir -p "$OUT/build" "$OUT/install"

if [ ! -d "$WINEPREFIX" ]; then
    if [ -n "${PREFIX_TEMPLATE:-}" ]; then
        cp -R "$PREFIX_TEMPLATE" "$WINEPREFIX"   # -R, not -a: the copy must belong to the running user
    else
        $WINE wineboot -i > "$OUT/wineboot.log" 2>&1
    fi
fi
# Only the drives we need: T: tools, S: source, O: output. Nothing else of the host.
rm -f "$WINEPREFIX/dosdevices/z:" "$WINEPREFIX"/dosdevices/*::
ln -sfn "$TOOLS" "$WINEPREFIX/dosdevices/t:"
ln -sfn "$SRC" "$WINEPREFIX/dosdevices/s:"
ln -sfn "$OUT" "$WINEPREFIX/dosdevices/o:"

export WINEPATH='T:\Qt\Tools\mingw492_32\bin;T:\Qt\5.6.3\mingw49_32\bin;T:\Tools;T:\GnuWin32\bin;T:\jdk1.8.0_112\bin'
export JAVA_HOME='T:\jdk1.8.0_112'
CMAKE='T:\CMake-3.20.1\bin\cmake.exe'
QT='T:\Qt\5.6.3\mingw49_32'

cd "$OUT/build"
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
    -DLauncher_BUILD_PLATFORM=win32 \
    -DLauncher_SUBREDDIT_URL="$SUBREDDIT_URL" \
    -DLauncher_DISCORD_URL="$DISCORD_URL" \
    -DLauncher_BUG_TRACKER_URL="$BUG_TRACKER_URL" \
    -DCMAKE_GP_CMD_PATHS=T:/Tools \
    -DCMAKE_GP_TOOL=dumpbin \
    ${CMAKE_EXTRA_ARGS:-} \
    'S:\' > "$OUT/configure.log" 2>&1 || { tail -40 "$OUT/configure.log"; exit 1; }

$WINE "$CMAKE" --build . -- -j"${JOBS:-$(nproc)}" > "$OUT/build.log" 2>&1 \
    || { grep -m30 -E "error|Error" "$OUT/build.log"; tail -20 "$OUT/build.log"; exit 1; }

$WINE 'T:\CMake-3.20.1\bin\ctest.exe' > "$OUT/test.log" 2>&1 || { tail -30 "$OUT/test.log"; echo "TESTS FAILED"; exit 1; }
tail -3 "$OUT/test.log"

$WINE "$CMAKE" --install . > "$OUT/install.log" 2>&1 || { tail -40 "$OUT/install.log"; exit 1; }
cp "$TOOLS/OpenSSL-Win32/libeay32.dll" "$TOOLS/OpenSSL-Win32/ssleay32.dll" "$OUT/install/MultiMC/"
echo "INSTALL OK"
