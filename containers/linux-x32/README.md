# linux-x32: lin32 toolchain

Image `multimc/toolchains/linux-x32:dev`: TeamCity's `linux-x32` image from the deth001
snapshot (Ubuntu 14.04 i386, g++-5, Qt 5.6.3 in `/opt/qt56`) plus CMake 3.10.0. The
snapshot has cmake 3.6.0; the Launcher requires 3.10 and Kitware ships no i386 binaries
after 3.6, so the Dockerfile builds it from source with the image's own g++-5 (no network
during the build) and installs it to `/`, like the lin64 image's cmake.

    zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-linux-x32.tar.zst | docker load
    grep " cmake-3.10.0.tar.gz$" cmake-3.10.0-SHA-256.txt | sha256sum -c -
    docker build -t multimc/toolchains/linux-x32:dev .

`cmake-3.10.0.tar.gz` and `cmake-3.10.0-SHA-256.txt` are from cmake.org. The build steps are
hopper's `build/linux.sh`.

History: the same fix was first made by hand (`docker commit`) on 2026-10-21 and loaded on
deth001, where TeamCity's Linux32 build uses it (archived as
`../archive/linux-x32-teamcity.tar.zst`). This Dockerfile reproduces it.

Verified 2026-10-21: builds develop 2a684511 with all tests passing, byte-identical binaries
to the hand-made image's build, same file list, system libraries and symbol versions (max
GLIBC_2.4, GLIBCXX_3.4.21) as the shipped `mmc-develop-lin32.tar.gz`.
