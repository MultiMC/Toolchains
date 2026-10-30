# syntax=docker/dockerfile:1
# MultiMC win32 toolchain: builds the win32 Launcher under Wine with the toolchain of the
# old Win7 build VM.
#
#   docker build -t multimc/toolchains/windows-win32:dev .
#
# Wine is GE-Proton10-15, the known-good Wine from the prototype (build.sh), copied in as-is
# and run the same way (files/bin/wine). No Wine packages from the distribution.
# Only the parts of Tools/ the build uses are copied in (.dockerignore):
# Qt 5.6.3 mingw49_32 + MinGW 4.9.2, CMake 3.20.1 (from the VM), GnuWin32 zlib,
# OpenSSL 1.0. dumpbin is our own stand-in (dumpbin/), built here with that MinGW; the JDK is
# Temurin 8 (tarballs/), in place of the VM's Oracle JDK 8u112.

FROM archlinux@sha256:e43f1fd80e073992c5f173efbbbf65144170bf60aeb7369940087d63eacea8f4

# Packages from a fixed Arch Linux Archive snapshot, so rebuilding gives the same image.
# GE-Proton's 32-bit side (files/bin/wine is an i386 launcher) needs the 32-bit C runtime.
ARG ARCHIVE_DATE=2026/10/20
RUN echo "Server = https://archive.archlinux.org/repos/${ARCHIVE_DATE}/\$repo/os/\$arch" > /etc/pacman.d/mirrorlist \
    && printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >> /etc/pacman.conf \
    && pacman -Syyuu --noconfirm lib32-glibc lib32-gcc-libs \
    && pacman -Scc --noconfirm

COPY GE-Proton10-15 /opt/ge-proton
COPY Tools /opt/win32/Tools

ENV WINE=/opt/ge-proton/files/bin/wine \
    WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=" HOME=/tmp \
    TOOLS=/opt/win32/Tools PREFIX_TEMPLATE=/opt/win32/prefix-template

# A ready-made Wine prefix; every build copies it fresh. Like build.sh: the libvkd3d DLLs
# are copied in by hand, because the prefix isn't made through Proton's own launcher script.
RUN WINEPREFIX=$PREFIX_TEMPLATE $WINE wineboot -i \
    && WINEPREFIX=$PREFIX_TEMPLATE /opt/ge-proton/files/bin/wineserver -w \
    && cp /opt/ge-proton/files/share/default_pfx/drive_c/windows/system32/libvkd3d*.dll $PREFIX_TEMPLATE/drive_c/windows/system32/ \
    && cp /opt/ge-proton/files/share/default_pfx/drive_c/windows/syswow64/libvkd3d*.dll $PREFIX_TEMPLATE/drive_c/windows/syswow64/ \
    && chmod -R a+rX $PREFIX_TEMPLATE

# dumpbin /dependents for the bundling (CMAKE_GP_TOOL=dumpbin, found in T:\Tools), built with
# the image's MinGW 4.9.2 in a throwaway copy of the prefix. See dumpbin/README.md.
COPY dumpbin/dumpbin.c /opt/win32/src/dumpbin.c
RUN cp -R $PREFIX_TEMPLATE /tmp/prefix \
    && mkdir -p $TOOLS/Tools \
    && WINEPREFIX=/tmp/prefix WINEPATH='Z:\opt\win32\Tools\Qt\Tools\mingw492_32\bin' \
        $WINE gcc -std=c89 -pedantic -Wall -Wextra -Werror -O2 -s \
        -o 'Z:\opt\win32\Tools\Tools\dumpbin.exe' 'Z:\opt\win32\src\dumpbin.c' \
    && WINEPREFIX=/tmp/prefix /opt/ge-proton/files/bin/wineserver -w \
    && rm -rf /tmp/prefix \
    && chmod -R a+rX $TOOLS/Tools

# JDK 8 for the Launcher's jars (javac -target 7, which newer JDKs refuse): Temurin, the same
# release as the macOS image. The build steps take its Windows path from JDK.
COPY tarballs/OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip /tmp/
RUN cd /tmp && echo "ea43d46ede95b51e44a12c66711706cddc762e0a766c54bccea18954e902b2aa  OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip" | sha256sum -c \
    && mkdir -p $TOOLS/jdk8 \
    && bsdtar -xf OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip --strip-components 1 -C $TOOLS/jdk8 \
    && rm OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip \
    && chmod -R a+rX $TOOLS/jdk8
ENV JDK='T:\jdk8'

LABEL org.opencontainers.image.title="MultiMC win32 toolchain (GE-Proton10-15)"
