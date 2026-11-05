# MultiMC Launcher toolchains

The toolchains needed to build the MultiMC Launcher (lin64, lin32, win32, win32-5.15.2,
osx64-5.15.2) without the old build machines, while staying compatible with every system
it supports today (Windows XP, macOS 10.13, old glibc), and the images of the tools the other release jobs run. Two parts:

| Directory | What | Changes |
|-----------|------|---------|
| [`snapshots/`](snapshots/README.md) | Raw captures of what was on the old machines: TeamCity's images and config, the shipped builds, the macmini, the Win7 build VM | Never modified. New capture = new dated directory. |
| [`containers/`](containers/README.md) | Sources for the toolchain and tool images, one directory per image, plus the archive of built images | When a toolchain or tool changes |

The flow: snapshots feed the container builds (base images, Qt, SDKs, the Windows
toolchain); the containers hold toolchains only. The build automation, [hopper](https://github.com/MultiMC/hopper),
is its own repo: it mounts the source and its build steps into the images, builds, packages,
and checks the result against the compatibility baselines taken from the shipped builds in
the snapshots.

Large files (images, archives, VM disks, the Windows toolchain tree) are not in git. They
are on the main dev machine and mirrored to `mikoshi:~/mirror/MultiMC-Toolchains` by
`./mirror.sh` (exact copy, `--delete`; `--dry-run` shows what would change; it verifies
every `SHA256SUMS` on the mirror afterwards). Every directory with large files has a
`SHA256SUMS` and a README saying where they came from.

## Published images

The images in `containers/` except `macos-osx64`, and the website's `site` image (from the
deth001 snapshot, see [`containers/README.md`](containers/README.md)), are published on GitHub's container
registry as `ghcr.io/multimc/toolchains/<name>:<date>`, so building the Launcher like the
releases doesn't need anything from the build server. hopper keeps using the local names
(`multimc/toolchains/<name>:dev`); to use a published image under that name:

    docker pull ghcr.io/multimc/toolchains/<name>@<digest>
    docker tag ghcr.io/multimc/toolchains/<name>@<digest> <name in hopper>

`macos-osx64` contains Apple's SDK, which can't be passed on: build it yourself, see
[its README](containers/macos-osx64/README.md#building-it-yourself).

Published 2026-10-30 (`ghcr.io/multimc/toolchains/<name>:2026-10-30`):

| Name | Name in hopper | Digest |
|------|----------------|--------|
| `linux-x64` | `multimc/toolchains/linux-x64:dev` (`IMAGE_LIN64`) | `sha256:7edb202c67b44e33b455fd89ac61d233bde534c5f127c10e6459a2c6c8548d35` |
| `linux-x32` | `multimc/toolchains/linux-x32:dev` (`IMAGE_LIN32`) | `sha256:ff4d98ca766647663bf570f2e73e25f1cc3272dcddb730d7181925bc3bf16002` |
| `windows-win32` | `multimc/toolchains/windows-win32:dev` (`IMAGE_WIN32`) | `sha256:f5712d15020fa1162344a8e076e6ba51e27914639237b5161031417aeb679378` |
| `translations` | `multimc/toolchains/translations:dev` (`IMAGE_TRANSLATIONS`) | `sha256:e8e6b13ae96b5e40d45293032b8b226ba28fd8ca959168743a6ed77c424ff251` |
| `deployer` | `multimc/toolchains/deployer:dev` (`IMAGE_DEPLOYER`) | `sha256:6c60c629023f2b930c37895f2a33dce190af04b4cf9d39a48f9bf2a8406ecd6e` |
| `site` | `ghcr.io/multimc/toolchains/site:latest` (`IMAGE_SITE`) | `sha256:fbb7c9283a1b770b05478814dabde6f19f1f0bf8028240443065567282890c39` |

`site` keeps its old name in hopper: tag it as `ghcr.io/multimc/toolchains/site:latest`
instead. The digests are the images' IDs as `docker image inspect` shows them with Docker's
containerd image store; rootless podman shows the image config's digest instead.

### Where the sources are

The images contain only freely redistributable software; for what is under the GPL or
similar licenses, these are the sources:

| Image | Contents | Sources |
|-------|----------|---------|
| `linux-x64`, `linux-x32` | Ubuntu 14.04 packages; Qt 5.6.3 (`/opt/qt56`) from the beineri/opt-qt563-trusty PPA; gcc 5 from the ubuntu-toolchain-r/test PPA; OpenJDK 8 from the openjdk-r PPA; CMake 3.10.0 | `deb-src http://archive.ubuntu.com/ubuntu trusty main universe`; the PPAs' source packages on Launchpad (`~beineri/+archive/ubuntu/opt-qt563-trusty`, `~ubuntu-toolchain-r/+archive/ubuntu/test`, `~openjdk-r/+archive/ubuntu/ppa`); cmake.org (`containers/linux-x32/cmake-3.10.0.tar.gz`) |
| `windows-win32` | Arch Linux (`lib32-glibc`, `lib32-gcc-libs`, Arch Linux Archive 2026/10/20); GE-Proton10-15; Qt 5.6.3 for MinGW and MinGW 4.9.2 (Qt's builds); CMake 3.20.1; GnuWin32 (zlib 1.2.3 and its tools); OpenSSL 1.0.2n; Temurin JDK 8u504; our `dumpbin` | Arch's package sources (`sources.archlinux.org`); github.com/GloriousEggroll/proton-ge-custom, tag GE-Proton10-15; download.qt.io/archive/qt/5.6/5.6.3; MinGW-builds i686 4.9.2 on sourceforge.net/projects/mingw-w64; cmake.org; gnuwin32.sourceforge.net; openssl.org; github.com/adoptium/jdk8u, tag jdk8u504-b01; `containers/windows-win32/dumpbin/` |
| `windows-win32-qt5.15` | `windows-win32`, plus Qt 5.15.2 for MinGW and MinGW 8.1.0 (Qt's builds); OpenSSL 1.1.1j (Qt's build); `msvcr100.dll` from the Visual C++ 2010 SP1 redistributable (Microsoft's, redistributable under its license terms, no source) | as `windows-win32`; download.qt.io/archive/qt/5.15/5.15.2 (`single/qt-everywhere-src-5.15.2`); MinGW-builds i686 8.1.0 on sourceforge.net/projects/mingw-w64; openssl.org |
| `translations`, `deployer` | Debian 12 packages; Qt 5.15.2 qtbase and qttools (built here); rclone 1.75.2; repoman2 | snapshot.debian.org; download.qt.io/archive/qt/5.15/5.15.2/submodules; github.com/rclone/rclone, tag v1.75.2; github.com/MultiMC/repoman2 |
| `site` | Ubuntu 24.04 packages; Hugo 0.31.1 | archive.ubuntu.com (noble); github.com/gohugoio/hugo, tag v0.31.1 |
