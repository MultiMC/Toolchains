# MultiMC lin32 toolchain: the TeamCity linux-x32 image as it was on deth001 (Ubuntu 14.04
# i386, g++-5, Qt 5.6.3 in /opt/qt56) plus CMake 3.10.0 built from source. The snapshot has
# cmake 3.6.0, too old for the Launcher since it requires 3.10, and Kitware ships no i386
# binaries after 3.6, so it is built here with the image's own g++-5, installed to / like
# the lin64 image's cmake.
#
#   zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-linux-x32.tar.zst | docker load
#   docker build -t multimc/toolchains/linux-x32:dev .
#
# cmake-3.10.0.tar.gz is from cmake.org; check it with cmake-3.10.0-SHA-256.txt.
FROM ghcr.io/multimc/toolchains/linux-x32:latest
COPY cmake-3.10.0.tar.gz /tmp/
RUN mkdir -p /tmp/b && cd /tmp/b && tar -xzf /tmp/cmake-3.10.0.tar.gz && cd cmake-3.10.0 \
    && CC=gcc-5 CXX=g++-5 ./bootstrap --prefix=/ --parallel="$(nproc)" -- \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_USE_OPENSSL=OFF -DBUILD_CursesDialog=OFF -DBUILD_QtDialog=OFF \
    && make -j"$(nproc)" && make install \
    && cd / && rm -rf /tmp/b /tmp/cmake-3.10.0.tar.gz \
    && cmake --version
LABEL org.opencontainers.image.title="MultiMC lin32 toolchain"
