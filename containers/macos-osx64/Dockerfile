# syntax=docker/dockerfile:1
# MultiMC macOS cross toolchain: builds the osx64-5.15.2 Launcher on Linux.
#
# Build with the macmini archive as a named context (it provides the Qt 5.15.2 itself):
#   docker build --build-context macarchive=../../snapshots/2026-10-21-macmini -t multimc/toolchains/macos-osx64:dev .
#
# Inputs in tarballs/ (all archived, see ../README.md):
#   MacOSX11.1.sdk.tar.xz                  SDK from macmini's Xcode 12.4 + its libc++ headers
#   qtbase-everywhere-src-5.15.2.tar.xz    for Linux-native moc/rcc/uic matching the macOS Qt
#   OpenJDK8U-jdk_x64_linux_hotspot_*.tar.gz   javac that can still emit -target 7

FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS base
ENV LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        clang llvm-dev lld cmake make git patch python3 perl ca-certificates \
        libxml2-dev libssl-dev liblzma-dev libbz2-dev zlib1g-dev uuid-dev xz-utils bzip2 cpio file \
    && rm -rf /var/lib/apt/lists/*

FROM base AS osxcross
ARG OSXCROSS_COMMIT=27d21e4977c9751d01199c7a226a6faf494c3dd9
RUN git clone https://github.com/tpoechtrager/osxcross /src/osxcross \
    && git -C /src/osxcross checkout ${OSXCROSS_COMMIT}
COPY tarballs/MacOSX11.1.sdk.tar.xz /src/osxcross/tarballs/
RUN cd /src/osxcross && UNATTENDED=1 TARGET_DIR=/opt/osxcross ./build.sh

FROM base AS qthost
COPY tarballs/qtbase-everywhere-src-5.15.2.tar.xz /src/
# Only the host tools moc/rcc/uic are built; they must match the macOS Qt version exactly.
# uic needs the widgets feature enabled, so gui/widgets stay on (minimal, offscreen, bundled 3rd party),
# but only the three tool targets are compiled.
# Qt 5.15.2 predates GCC 11's leaner headers, hence the added <limits>.
RUN cd /src && tar -xf qtbase-everywhere-src-5.15.2.tar.xz && cd qtbase-everywhere-src-5.15.2 \
    && sed -i 's|#include <algorithm>|#include <algorithm>\n#include <limits>|' src/corelib/global/qglobal.h \
    && ./configure -prefix /opt/qt5-host -release -opensource -confirm-license -platform linux-clang \
        -nomake examples -nomake tests -qpa offscreen -no-xcb -no-opengl -no-dbus -no-icu -no-openssl \
        -no-fontconfig -qt-freetype -qt-harfbuzz -qt-pcre -qt-zlib -qt-libpng -qt-libjpeg \
    && make sub-src-qmake_all \
    && for t in sub-moc sub-rcc sub-uic; do make -j"$(nproc)" -C src $t || exit 1; done \
    && mkdir -p /opt/qt5-host/bin /opt/qt5-host/lib && cp bin/moc bin/rcc bin/uic /opt/qt5-host/bin/ \
    && cp -a lib/libQt5Core.so* /opt/qt5-host/lib/ \
    && /opt/qt5-host/bin/moc -v && /opt/qt5-host/bin/rcc -v && /opt/qt5-host/bin/uic -v

FROM base
COPY --from=osxcross /opt/osxcross /opt/osxcross
COPY --from=qthost /opt/qt5-host /opt/qt5-host
COPY tarballs/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz /tmp/
RUN mkdir -p /opt/jdk8 && tar -C /opt/jdk8 --strip-components=1 -xzf /tmp/OpenJDK8U-*.tar.gz && rm /tmp/OpenJDK8U-*.tar.gz
ENV PATH=/opt/osxcross/bin:/opt/jdk8/bin:$PATH JAVA_HOME=/opt/jdk8

# The macmini's Qt 5.15.2 clang_64 at its original path, with the Linux moc/rcc/uic and the
# qmake stand-in (prepare-qt.sh). The archive is mounted, not copied into a layer.
# The CMake toolchain file used by the build (hopper's build/osx64.sh).
COPY toolchain-osx64.cmake /opt/toolchain-osx64.cmake
COPY prepare-qt.sh /opt/prepare-qt.sh
RUN apt-get update && apt-get install -y --no-install-recommends zstd && rm -rf /var/lib/apt/lists/*
RUN --mount=type=bind,from=macarchive,target=/archive \
    ARCHIVE=/archive QT_ROOT=/ /opt/prepare-qt.sh \
    && /Users/peterix/Qt/5.15.2/clang_64/bin/moc -v
LABEL org.opencontainers.image.title="MultiMC macOS cross toolchain (osx64-5.15.2)"
