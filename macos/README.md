# macOS toolchain

Everything needed to build the `osx64-5.15.2` Launcher without the macmini, on Linux.

## 2026-10-21/ — archive of the macmini

Taken over SSH from macmini.peterix.cz (Macmini7,1, macOS 11.6, Xcode 12.4) on 2026-10-21.
`SHA256SUMS` covers the tarballs; `MANIFEST.txt` records the machine state (OS, Xcode,
SDK list, clang, cmake, Java, `qmake -query` for both Qts, TeamCity agent config).

| File | Contents |
|------|----------|
| `macmini-Qt.tar.zst` | `/Users/peterix/Qt`: Qt 5.15.2 `clang_64` (current channel) and 5.6.3 `clang_64` (frozen `osx64` channel), plus the Qt installer files |
| `macmini-CMake.app.tar.zst` | `/Applications/CMake.app` (CMake 3.20.0, used by the TeamCity agent) |
| `xcode-12.4-sdks.tar.zst` | Xcode's macOS SDKs: 11.1 (`MacOSX.sdk`), plus 10.7 and 10.8 that were copied in by hand for the old 10.7-compatible builds |
| `xcode-12.4-toolchain-libcxx-clangrt.tar.zst` | Xcode toolchain libc++ headers, clang 12 runtime libs, libarclite |

Archives were made with macOS `tar`, so they contain AppleDouble `._*` entries and
`SCHILY.fflags` headers. On Linux extract with `--exclude='._*' --warning=no-unknown-keyword`.
Paths are kept absolute (Qt has its install prefix compiled in).

## cross/ — Linux cross build (osxcross)

Produces the same app as the TeamCity macOS build: x86_64, minimum macOS 10.13, SDK 11.1,
same bundle contents. Verified 2026-10-21 against the shipped `mmc-develop-osx64-5.15.2`
(see "Verification" below).

### Pieces

| Piece | What / why |
|-------|------------|
| `Dockerfile` | The toolchain image `multimc/toolchains/macos-cross`. Base image pinned by digest, osxcross pinned by commit. Three stages: **osxcross** (clang wrappers, Apple cctools/ld64 port, against our SDK), **qthost** (Linux `moc`/`rcc`/`uic` built from the exact Qt 5.15.2 source, because the archived Qt's tools are macOS binaries and generated code must match the Qt version), and the final image which adds **Temurin JDK 8** (the Launcher's jars are compiled with `-target 7`, which newer JDKs refuse). |
| `tarballs/MacOSX11.1.sdk.tar.xz` | Made by `make-sdk-package.sh` from the archive: SDK 11.1 with Xcode's libc++ headers merged into `usr/include/c++/v1` (Xcode 12 keeps them in the toolchain). Deterministic; expected SHA-256 in `tarballs/SHA256SUMS`. |
| `tarballs/qtbase-everywhere-src-5.15.2.tar.xz` | From download.qt.io, MD5 checked against Qt's `md5sums.txt`. |
| `tarballs/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz` | From Adoptium, SHA-256 checked against the Adoptium API. |
| `prepare-qt.sh` | Installs the archived macmini Qt 5.15.2 into the image at its original path `/Users/peterix/Qt/5.15.2/clang_64`: original macOS tools moved to `bin.macos/`, `moc`/`rcc`/`uic` linked to the image's Linux builds, and a `qmake` stand-in that answers the `-query` calls the Launcher's CMake makes. Run during the image build (`QT_ROOT=/`); can also make a host copy in `work/qt`. |
| `toolchain-osx64.cmake` | Includes osxcross's toolchain file, then lets `find_package` see Qt outside the SDK. Libraries and headers still come only from the SDK. |
| `build-osx64.sh` | The build: same CMake options as TeamCity (`mac-bundle`, deployment target 10.13, Release), no network, as the calling user. `SOURCE_DATE_EPOCH` is set to the commit time, because Qt 5.15's `rcc` embeds file modification times in resources; with it, two checkouts of the same commit build byte-identical apps. Two cross-build specifics: `otool`/`install_name_tool` are put on `PATH` under their plain names for CMake's BundleUtilities, and the install step runs with `-DAPPLE=1` because CMake's script mode doesn't set it on a Linux host. |

### From scratch

    ./make-sdk-package.sh                # needs ../2026-10-21
    sha256sum -c tarballs/SHA256SUMS
    docker build --build-context macarchive=../2026-10-21 -t multimc/toolchains/macos-cross:dev .
    ./build-osx64.sh <Launcher checkout on its branch, with submodules> <out dir> <build number>

The image contains everything, including the Qt 5.15.2 (mounted from the macmini archive
during the image build, not copied into a layer).

Result: `<out>/install/MultiMC.app`, logs in `<out>/*.log`.

The built image is also archived as `../../images/candidates/macos-cross-osx64.tar.zst` — loading that is the
fallback if osxcross's own dependencies (fetched from GitHub during `docker build`) ever
disappear.

### Verification (2026-10-21, Launcher develop 2a684511, image built from the scripted inputs)

Compared with the shipped `mmc-develop-osx64-5.15.2.tar.gz` (in `../../baselines/2026-10-21/`):

- identical bundle file list
- main binary links exactly the same libraries in the same order
- all 25 Mach-O files: x86_64, `LC_VERSION_MIN_MACOSX` 10.13; the 5 we build have SDK 11.1,
  the 20 prebuilt Qt frameworks/plugins SDK 10.14 — the same split as the shipped build
- no dependencies outside the bundle and `/usr/lib`, `/System`
- git commit embedded (built from a clean checkout)
- launched on the macmini (macOS 11.6) in the GUI session with a scratch data dir: initialises and runs

Not covered: the unit tests (they are macOS binaries; would need running on a Mac), and
launching on macOS 10.13 itself.

### Not done yet

- **arm64**: osxcross and SDK 11.1 already support it (`OSXCROSS_SUPPORTED_ARCHS` includes
  arm64). Missing: a Qt 5.15 built for arm64 (the official 5.15.2 binaries are x86_64 only;
  plan is to build it once on an Apple Silicon Mac and archive it like the macmini Qt), and
  ad-hoc code signing (arm64 code must be signed; e.g. `rcodesign` on Linux). Then lipo
  both into a universal app.
- **frozen `osx64` (Qt 5.6.3, macOS 10.7)**: the Qt and the 10.7 SDK are archived, but no
  cross build is set up for it.
