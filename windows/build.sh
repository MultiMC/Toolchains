#!/bin/bash

set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd ${SCRIPT_DIR}

################################################################################
##    Config
################################################################################

# Wine / Proton
WINE_ROOT="${SCRIPT_DIR}/GE-Proton10-15"
WINE_BIN="${WINE_ROOT}/files/bin"
WINE="${WINE_BIN}/wine"
export WINEPREFIX="${SCRIPT_DIR}/WineRoot"
export WINEDEBUG=-all
export LD_PRELOAD=""

# JDK 8
export JAVA_HOME="T:\\jdk1.8.0_112"
export JRE_HOME="${JAVA_HOME}\\jre"

# Misc tools
TOOLS_PATH="T:\\Tools"
TOOLS_PATH_CMAKE="T:/Tools"

################################################################################
##    Setting up wine prefix
################################################################################

if [ ! -d "${WINEPREFIX}" ];
then
    echo "${WINEPREFIX} does not exist. Setting up a fresh prefix..."
    rm -rf "${WINEPREFIX}"

    ${WINE} wineboot

    # Remove auto-created pointless drives that expose the system
    rm -f "${WINEPREFIX}/dosdevices/z:"
    rm -f "${WINEPREFIX}/dosdevices/"*::

    # Add drives for tools and source/build artifacts
    ln -s ../../Tools "${WINEPREFIX}/dosdevices/t:"
    ln -s ../../Data "${WINEPREFIX}/dosdevices/d:"

    # ugly workaround for missing files
    # the issue comes fro us not using the `proton` script to start this
    cp "${WINE_ROOT}/files/share/default_pfx/drive_c/windows/system32/"libvkd3d*.dll "${WINEPREFIX}/drive_c/windows/system32/"
    cp "${WINE_ROOT}/files/share/default_pfx/drive_c/windows/syswow64/"libvkd3d*.dll "${WINEPREFIX}/drive_c/windows/syswow64/"
fi

################################################################################
##    Build
################################################################################
build_windows () {
    mkdir -p ${SCRIPT_DIR}/Data/${PLATFORM}/Build/
    cd ${SCRIPT_DIR}/Data/${PLATFORM}/Build

    # Configure
    ${WINE} T:\\CMake\\bin\\cmake.exe \
    -DCMAKE_MAKE_PROGRAM="mingw32-make" \
    -DCMAKE_C_COMPILER="gcc" \
    -DCMAKE_CXX_COMPILER="g++" \
    -DCMAKE_BUILD_TYPE=Debug \
    -DLauncher_NOTIFICATION_URL:STRING=https://files.multimc.org/notifications.json \
    -DCMAKE_INSTALL_PREFIX:PATH="D:\\${PLATFORM}\\install\\MultiMC" \
    -DCMAKE_PREFIX_PATH="${QT_PATH}" \
    -DQt5_DIR="${QT_PATH}" \
    -DLauncher_UPDATER_BASE=https://files.multimc.org/update/ \
    -DLauncher_PASTE_EE_API_KEY:STRING=utLvciUouSURFzfjPxLBf5W4ISsUX4pwBDF7N1AfZ \
    -DLauncher_ANALYTICS_ID:STRING=UA-87731965-2 \
    -DLauncher_LAYOUT=win-bundle \
    -DLauncher_VERSION_BUILD=4248 \
    -DLauncher_BUILD_PLATFORM=${PLATFORM} \
    -DLauncher_SUBREDDIT_URL=https://www.reddit.com/r/MultiMC/ \
    -DLauncher_DISCORD_URL=https://discord.gg/multimc \
    -DLauncher_BUG_TRACKER_URL=https://github.com/MultiMC/Launcher/issues \
    -DLauncher_EMBED_SECRETS=On \
    -G "MinGW Makefiles" \
    -DCMAKE_GP_CMD_PATHS="${TOOLS_PATH_CMAKE}" \
    -DCMAKE_GP_TOOL="dumpbin" \
    -DZLIB_ROOT="${ZLIB_PATH}" \
    "..\\..\\Launcher"

    # Build
    ${WINE} T:\\CMake\\bin\\cmake.exe --build . -- -j$(nproc)

    # Test
    export WINEPATH="${TOOLCHAIN_PATH};${TOOLS_PATH};${QT_BINPATH};${ZLIB_BIN_PATH}"
    echo "WINEPATH: ${WINEPATH}"
    ${WINE} T:\\CMake\\bin\\ctest.exe -V

    # Install
    rm -rf "${SCRIPT_DIR}/Data/install/MultiMC"
    ${WINE} T:\\CMake\\bin\\cmake.exe --install .
    cp "${OPENSSL_PATH}/"*.dll "${SCRIPT_DIR}/Data/${PLATFORM}/install/MultiMC/"
}

build_win32 () {
    # Qt 5.6.3
    ##########
    PLATFORM="win32"
    TOOLCHAIN_PATH="T:\\Qt\\Tools\\mingw492_32\\bin"
    QT_PATH="T:\\Qt\\5.6.3\\mingw49_32"
    OPENSSL_PATH="${SCRIPT_DIR}/Tools/OpenSSL-Win32"
    QT_BINPATH="${QT_PATH}\\bin"
    ZLIB_PATH="T:\\GnuWin32"
    ZLIB_BIN_PATH="${ZLIB_PATH}\\bin"

    export WINEPATH="${TOOLCHAIN_PATH};${TOOLS_PATH};${JAVA_HOME}\bin"
    build_windows
}

build_win32-5.15.2 () {
    # Qt 5.15.2
    ###########
    PLATFORM="win32-5.15.2"
    TOOLCHAIN_PATH="T:\\QtX\\Tools\\mingw810_32\\bin"
    QT_PATH="T:\\QtX\\5.15.2\\mingw81_32"
    OPENSSL_PATH="${SCRIPT_DIR}/Tools/QtX/Tools/OpenSSL/Win_x86/bin"
    QT_BINPATH="${QT_PATH}\\bin"
    ZLIB_PATH="T:\\GnuWin32"
    ZLIB_BIN_PATH="${ZLIB_PATH}\\bin"

    export WINEPATH="${TOOLCHAIN_PATH};${TOOLS_PATH};${JAVA_HOME}\bin"
    build_windows
}

build_win32

# This doesn't work
#build_win32-5.15.2
