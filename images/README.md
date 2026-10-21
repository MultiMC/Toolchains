# Toolchain image archive

These images are the only authoritative copies of the build environments.
The Dockerfiles in `../agents/` and `../old/` do NOT reproduce them (the real
images pull Qt 5.6.3 from the beineri `opt-qt563-trusty` PPA and packages from
Ubuntu ESM). Never rebuild them; load these tarballs instead.

## 2026-10-21/

`docker save` of `ghcr.io/multimc/toolchains/*:latest` as they were on
deth001.multimc.org that day, zstd-compressed. `IMAGES.txt` has the image IDs
and registry digests on deth001; `SHA256SUMS` covers the tarballs.

    zstd -dc toolchains-linux-x64.tar.zst | docker load

| Image      | Contents |
|------------|----------|
| linux-x64  | Ubuntu 14.04 amd64, glibc 2.19, g++-5.5, Qt 5.6.3 (/opt/qt56), cmake 3.10.0, OpenJDK 8 |
| linux-x32  | Same, i386 userland, cmake 3.6.0 (too old for the Launcher since the cmake 3.10 bump) |
| deployer   | Ubuntu, repoman2, s3cmd, patron updater |
| site       | hugo 0.31.1 |
| windows    | Arch + wine + the Windows Tools tree (prototype, never pushed to ghcr) |

## candidates/

`linux-x32-cmake-3.10.0.tar.zst` — the 2026-10-21 linux-x32 image plus CMake
3.10.0 built from the official source (`cmake-3.10.0.tar.gz`, SHA-256 checked
against `cmake-3.10.0-SHA-256.txt`) with the image's own g++-5, installed to
`/` like the x64 image's cmake. Tag: `ghcr.io/multimc/toolchains/linux-x32:cmake-3.10.0`.

Built inside the container with no network:

    CC=gcc-5 CXX=g++-5 ./bootstrap --prefix=/ -- -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_USE_OPENSSL=OFF -DBUILD_CursesDialog=OFF -DBUILD_QtDialog=OFF
    make && make install

Verified 2026-10-21 against Launcher develop 2a684511 (Release, lin-nodeps):
all 15 tests pass, and the install tree matches the shipped
`mmc-develop-lin32.tar.gz` in file list, NEEDED libs and max symbol versions
(GLIBC_2.4, GLIBCXX_3.4.21, CXXABI_1.3, GCC_3.0).

`windows-win32.tar.zst` — `multimc/toolchains/windows-win32:dev`, the win32 build under
Wine (minimal Arch + GE-Proton10-15 + the VM's toolchain). See `../windows/README.md`.

`macos-cross-osx64.tar.zst` — `multimc/toolchains/macos-cross:dev`, see `../macos/README.md`.

`translations.tar.zst` — `multimc/toolchains/translations:dev`, see `../translations/README.md`.

## ../baselines/

Shipped builds copied from files.multimc.org/downloads, used as the reference
for compatibility checks:

| Channel        | Facts |
|----------------|-------|
| lin32          | i386, max GLIBC_2.4 / GLIBCXX_3.4.21 |
| lin64          | x86-64, max GLIBC_2.14 / GLIBCXX_3.4.21 |
| win32          | PE OS/subsystem version 4.0 (XP), Qt 5.6.3, OpenSSL 1.0 (libeay32/ssleay32) |
| osx64-5.15.2   | Qt 5.15.2, minos 10.13, SDK 11.1 |
| osx64 (frozen) | Qt 5.6.3, minos 10.7, last stable 2023-02-04 |
