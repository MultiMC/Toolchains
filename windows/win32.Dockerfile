# syntax=docker/dockerfile:1
# MultiMC win32 toolchain: builds the win32 Launcher under Wine with the toolchain of the
# old Win7 build VM.
#
#   docker build -f win32.Dockerfile -t multimc/toolchains/windows-win32:dev .
#
# Wine is GE-Proton10-15, the known-good Wine from the prototype (build.sh), copied in as-is
# and run the same way (files/bin/wine). No Wine packages from the distribution.
# Only the parts of Tools/ the build uses are copied in (win32.Dockerfile.dockerignore):
# Qt 5.6.3 mingw49_32 + MinGW 4.9.2, CMake 3.20.1 (from the VM), dumpbin/link, GnuWin32
# zlib, OpenSSL 1.0, JDK 8u112.

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
COPY build-win32.sh /opt/win32/build-win32.sh

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

LABEL org.opencontainers.image.title="MultiMC win32 toolchain (GE-Proton10-15)"
ENTRYPOINT ["/opt/win32/build-win32.sh"]
