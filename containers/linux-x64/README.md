# linux-x64: lin64 toolchain

Image `multimc/toolchains/linux-x64:dev`: TeamCity's `linux-x64` image from the deth001
snapshot, unchanged (Ubuntu 14.04, glibc 2.19, g++-5.5, Qt 5.6.3 in `/opt/qt56`,
cmake 3.10.0, OpenJDK 8). It can't be rebuilt from its original recipe (Ubuntu ESM, PPAs),
so the snapshot image is the source; this directory only gives it the uniform name.

    zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-linux-x64.tar.zst | docker load
    docker build -t multimc/toolchains/linux-x64:dev .

Not archived separately: it is the snapshot image. The build steps are
`../../automation/build/linux.sh`.

Verified 2026-10-21: builds develop 2a684511 with all tests passing, same file list, same
system libraries and symbol versions (max GLIBC_2.14, GLIBCXX_3.4.21) as the shipped
`mmc-develop-lin64.tar.gz`.
