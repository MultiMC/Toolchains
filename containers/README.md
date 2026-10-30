# Containers

Sources for the toolchain images, one directory per image. Image name:
`multimc/toolchains/<directory>:dev`. Each directory has a `Dockerfile`, its inputs and a
README with how it was made and verified.

Kind: **preserved** means made from what was on the old machines, kept on purpose for
compatibility (Windows XP, old macOS, old glibc) and not to be replaced; **primary** means
built from upstream sources and pinned inputs.

| Directory | Image for | Kind | Made from |
|-----------|-----------|------|-----------|
| [`linux-x64/`](linux-x64/README.md) | lin64 | preserved | the deth001 snapshot image, unchanged (Ubuntu 14.04, glibc 2.19, g++-5, Qt 5.6.3 from a PPA); can't be rebuilt from its recipe |
| [`linux-x32/`](linux-x32/README.md) | lin32 | preserved, one primary input | the deth001 snapshot image (i386) + CMake 3.10.0 built from cmake.org's source |
| [`windows-win32/`](windows-win32/README.md) | win32 | preserved toolchain on a primary base | Arch pinned by digest + Arch Linux Archive snapshot; GE-Proton10-15 copied as-is from the prototype; the Win7 VM's `Tools/` (Qt 5.6.3, MinGW 4.9.2, CMake 3.20.1, MSVC dumpbin/link, OpenSSL 1.0, JDK 8u112), hash-verified against the VM disk |
| [`macos-osx64/`](macos-osx64/README.md) | osx64-5.15.2 | preserved SDK and Qt on a primary base | Debian pinned by digest, osxcross pinned by commit, qtbase 5.15.2 source, Temurin JDK 8; the macmini's SDK 11.1 (Xcode 12.4) and Qt 5.15.2 clang_64; can't be published (Apple's SDK), but anyone can [build it](macos-osx64/README.md#building-it-yourself) from Xcode 12.4 and Qt's own archives |
| [`translations/`](translations/README.md) | the translations repo's tooling | primary | Debian pinned by digest + Qt 5.15.2 qtbase/qttools source |
| [`deployer/`](deployer/README.md) | hopper's deploy and publish steps | primary | Debian 12 (python3) + rclone 1.75.2 from rclone.org + repoman2 4ce9a73; until 2026-10-30 the deth001 snapshot image + upstream rclone |

Images used without a directory here, straight from `../snapshots/2026-10-21-deth001/images`:

| Snapshot image | Status |
|----------------|--------|
| `toolchains-site` (Hugo 0.31.1) | in use, preserved: hopper's `website/build.py` runs `ghcr.io/multimc/toolchains/site:latest` (`IMAGE_SITE`). A candidate for a primary rebuild, as Hugo is a single upstream binary. |
| `toolchains-windows` | unused (an experiment, never pushed) |

## What the images contain

Toolchains only: no build steps, no entrypoint. The build steps are in
hopper's `build/`, and its `run-build.py` runs every platform the same way
([hopper](https://github.com/MultiMC/hopper)):

    docker run --rm --network none -u <uid>:<gid> \
        -v <source>:/src:ro -v <output>:/out -v hopper/build:/build:ro <settings> \
        <image> bash /build/<platform script>

So a change to the build steps never needs an image rebuild; images change only when a
toolchain does.

## `archive/`

`docker save` of the built images, zstd-compressed (not in git; `SHA256SUMS` is). Load with
`zstd -dc <name>.tar.zst | docker load`. The fallback if an image can't be rebuilt (e.g.
osxcross fetches its own dependencies from GitHub during the build).

| File | Image |
|------|-------|
| `linux-x32.tar.zst` | `multimc/toolchains/linux-x32:dev` |
| `windows-win32.tar.zst` | `multimc/toolchains/windows-win32:dev` |
| `macos-osx64.tar.zst` | `multimc/toolchains/macos-osx64:dev` |
| `translations.tar.zst` | `multimc/toolchains/translations:dev` (also running on deth001) |
| `linux-x32-teamcity.tar.zst` | `ghcr.io/multimc/toolchains/linux-x32:cmake-3.10.0`, the hand-made fix TeamCity's Linux32 build uses on deth001 until the cutover |

`linux-x64` isn't archived separately: it is the snapshot image.
