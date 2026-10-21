# syntax=docker/dockerfile:1
# MultiMC translation tools: Qt 5.15.2 linguist tools (lupdate, lconvert, lrelease),
# gettext and python3, for the MultiMC5-translate repo's update.sh / release.sh.
#
# Why 5.15.2 and not the 5.6.3 tools in the linux-x64 image: Qt 5.6's lupdate does not
# understand C++11 raw string literals and silently stops extracting a file after one
# (17 strings in MainWindow.cpp were never translatable). See README.md.
#
# Inputs in tarballs/ (SHA256SUMS; MD5 checked against download.qt.io md5sums.txt):
#   qtbase-everywhere-src-5.15.2.tar.xz, qttools-everywhere-src-5.15.2.tar.xz

FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587 AS base
ENV LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        gettext python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM base AS build
RUN apt-get update && apt-get install -y --no-install-recommends clang make perl python3 xz-utils \
    && rm -rf /var/lib/apt/lists/*
COPY tarballs/qtbase-everywhere-src-5.15.2.tar.xz tarballs/qttools-everywhere-src-5.15.2.tar.xz /src/
# QtCore + QtXml only (no gui), enough for the command-line linguist tools.
# Qt 5.15.2 predates GCC 11's leaner headers, hence the added <limits>.
RUN cd /src && tar -xf qtbase-everywhere-src-5.15.2.tar.xz && cd qtbase-everywhere-src-5.15.2 \
    && sed -i 's|#include <algorithm>|#include <algorithm>\n#include <limits>|' src/corelib/global/qglobal.h \
    && ./configure -prefix /opt/qt5152 -release -opensource -confirm-license -platform linux-clang \
        -nomake examples -nomake tests -no-gui -no-widgets -no-dbus -no-opengl -no-icu -no-openssl \
        -qt-pcre -qt-zlib \
    && make -j"$(nproc)" && make install
RUN cd /src && tar -xf qttools-everywhere-src-5.15.2.tar.xz && cd qttools-everywhere-src-5.15.2 \
    && /opt/qt5152/bin/qmake && make qmake_all \
    && make -j"$(nproc)" -C src/linguist && make -C src/linguist install \
    && /opt/qt5152/bin/lupdate -version && /opt/qt5152/bin/lconvert -h >/dev/null && /opt/qt5152/bin/lrelease -version

FROM base
COPY --from=build /opt/qt5152/bin/lupdate /opt/qt5152/bin/lconvert /opt/qt5152/bin/lrelease /opt/qt5152/bin/
COPY --from=build /opt/qt5152/lib/libQt5Core.so.5 /opt/qt5152/lib/libQt5Xml.so.5 /opt/qt5152/lib/
ENV PATH=/opt/qt5152/bin:$PATH

# The Update Template job commits and pushes template.pot over SSH (TeamCity provides the key).
# github_known_hosts is GitHub's RSA host key, taken from the old linux-x64 image and checked
# against https://api.github.com/meta (SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s).
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY github_known_hosts /etc/ssh/ssh_known_hosts
# TeamCity runs the container as root on a checkout owned by the agent user; git >= 2.35.2
# refuses that ("dubious ownership"). The container only ever sees its own build checkout.
RUN git config --system --add safe.directory '*'
LABEL org.opencontainers.image.title="MultiMC translation tools (Qt 5.15.2 linguist)"
