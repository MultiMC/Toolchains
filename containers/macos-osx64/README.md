# macos-osx64: osx64-5.15.2 toolchain (cross-build on Linux)

Image `multimc/toolchains/macos-osx64:dev`. Builds the macOS Launcher on Linux with
osxcross, the Xcode 12.4 SDK 11.1 and the macmini's Qt 5.15.2, replacing the macmini.
Produces the same app as the TeamCity macOS build: x86_64, minimum macOS 10.13, SDK 11.1.

    ./make-sdk-package.sh
    sha256sum -c tarballs/SHA256SUMS
    docker build --build-context macarchive=../../snapshots/2026-10-21-macmini \
        -t multimc/toolchains/macos-osx64:dev .

The build steps are hopper's `build/osx64.sh`.

## Pieces

| Piece | What / why |
|-------|------------|
| `Dockerfile` | Base image pinned by digest, osxcross pinned by commit. Stages: **osxcross** (clang wrappers, Apple cctools/ld64 port, against our SDK), **qthost** (Linux `moc`/`rcc`/`uic` built from the exact Qt 5.15.2 source: the archived Qt's tools are macOS binaries, and generated code must match the Qt version), and the final image with **Temurin JDK 8** (the Launcher's jars use `-target 7`, which newer JDKs refuse), the Qt 5.15.2 and the CMake toolchain file. |
| `tarballs/MacOSX11.1.sdk.tar.xz` | Made by `make-sdk-package.sh` from the macmini snapshot: SDK 11.1 with Xcode's libc++ headers merged into `usr/include/c++/v1` (Xcode 12 keeps them in the toolchain). Deterministic; expected SHA-256 in `tarballs/SHA256SUMS`. |
| `tarballs/qtbase-everywhere-src-5.15.2.tar.xz` | From download.qt.io, MD5 checked against Qt's `md5sums.txt`. |
| `tarballs/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz` | From Adoptium, SHA-256 checked against the Adoptium API. |
| `prepare-qt.sh` | Installs the Qt 5.15.2 (the macmini's, or Qt's own archives unpacked) at the macmini's original path `/Users/peterix/Qt/5.15.2/clang_64` during the image build (the snapshot is mounted, not copied into a layer): original macOS tools moved to `bin.macos/`, `moc`/`rcc`/`uic` linked to the Linux builds, a `qmake` stand-in that answers the `-query` calls the Launcher's CMake makes. |
| `qt-5.15.2-clang_64.sha1` | The 25 archives of Qt's `qt.qt5.5152.clang_64` package (5.15.2-0-202011130601) on download.qt.io, the ones the macmini's Qt was installed from. For building the image without the snapshot. |
| `toolchain-osx64.cmake` | Installed as `/opt/toolchain-osx64.cmake`. Includes osxcross's toolchain file, then lets `find_package` see Qt outside the SDK; libraries and headers still come only from the SDK. |

Cross-build specifics handled by the build steps: `otool`/`install_name_tool` under their
plain names for CMake's BundleUtilities, the install step run with `-DAPPLE=1` (CMake's
script mode doesn't set it on Linux), and a fixed `SOURCE_DATE_EPOCH` (Qt 5.15's `rcc`
embeds file modification times; fixed, two checkouts and clean vs incremental builds give
byte-identical apps).

## Building it yourself

This image can't be published: it contains Apple's macOS SDK, which the Xcode license
doesn't allow passing on. Everything else is public, so you can build it yourself on Linux
with Docker. You need an Apple ID (free) and, for one step, a Mac.

1. **The SDK, from Xcode 12.4.** Download `Xcode_12.4.xip` from
   <https://developer.apple.com/download/all/>. On a Mac, unpack it (`xip --expand
   Xcode_12.4.xip`) and pack the two parts the SDK is made from, without macOS's `._` files:

       COPYFILE_DISABLE=1 tar -cf xcode-12.4-parts.tar \
           Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk \
           Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/include/c++/v1

   On Linux, unpack that and make the SDK package from it:

       mkdir ~/xcode-12.4 && tar -C ~/xcode-12.4 -xf xcode-12.4-parts.tar --exclude='._*'
       XCODE=~/xcode-12.4/Xcode.app ./make-sdk-package.sh

2. **The other inputs** in `tarballs/`, from their upstreams:

       curl -fL -o tarballs/qtbase-everywhere-src-5.15.2.tar.xz \
           https://download.qt.io/archive/qt/5.15/5.15.2/submodules/qtbase-everywhere-src-5.15.2.tar.xz
       curl -fL -o tarballs/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz \
           https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u504-b01/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz

   Then check all three, the SDK included. Every line must say `OK`; if the SDK doesn't,
   it isn't the SDK the releases are built with, so stop there:

       (cd tarballs && sha256sum -c SHA256SUMS)

3. **Qt 5.15.2 for macOS**, from Qt's repository (no installer or Qt account needed), into a
   directory of its own; `bsdtar` is in Debian's `libarchive-tools` (`7z x` works too):

       mkdir ~/qt-5.15.2 && cd ~/qt-5.15.2
       B=https://download.qt.io/online/qtsdkrepository/mac_x64/desktop/qt5_5152/qt.qt5.5152.clang_64
       for f in $(cut -d' ' -f3 <toolchains>/containers/macos-osx64/qt-5.15.2-clang_64.sha1); do curl -fLO "$B/$f"; done
       sha1sum -c <toolchains>/containers/macos-osx64/qt-5.15.2-clang_64.sha1
       for f in *.7z; do bsdtar -xf "$f" --no-same-owner; done

   That gives `~/qt-5.15.2/5.15.2/clang_64`. A Qt installer's `~/Qt` with 5.15.2 macOS
   works too.

4. **The image**, back in this directory (osxcross is cloned from GitHub during the build):

       docker build --build-context macarchive=$HOME/qt-5.15.2 -t multimc/toolchains/macos-osx64:dev .

Then build with hopper's `launcher/run-build.py osx64-5.15.2 <Launcher checkout> <output>`
and check the result with its `launcher/compat-check.py` (see the hopper README).

Checked on 2026-10-30: `make-sdk-package.sh` makes the identical SDK package from an
`Xcode.app` laid out like step 1 (built from the snapshot's Xcode files); Qt's 25 archives
unpacked are the macmini's Qt file for file, except the two `qt.conf` files and the edition
line in `mkspecs/qconfig.pri` that Qt's installer writes (read only by qmake, which the image
replaces); an image built from them builds develop da162756 identically to this one (same 48
files, all binaries byte-identical, jar contents identical, the gate passes). Not tried yet:
step 1 with a freshly downloaded `Xcode_12.4.xip`; the SDK checksum in step 2 is what tells.

## Verification (2026-10-21, develop 2a684511)

Against the shipped `mmc-develop-osx64-5.15.2.tar.gz` (`snapshots/2026-10-21-deth001/downloads`):

- identical bundle file list; the main binary links the same libraries in the same order
- all 25 Mach-O files x86_64, minimum macOS 10.13; the 5 we build have SDK 11.1, the 20
  prebuilt Qt frameworks/plugins SDK 10.14, the same split as the shipped build
- nothing linked outside the bundle, `/usr/lib`, `/System`; the commit is embedded; the
  updater and notification URLs are embedded (an early version lacked them, see
  hopper's `README.md`)
- launched on the macmini (macOS 11.6) in its GUI session: initialises and runs

Not covered: the unit tests (macOS binaries) and running on macOS 10.13 itself.

## Not done yet

- **arm64**: osxcross and SDK 11.1 support it. Missing: a Qt 5.15 built for arm64 (the
  official 5.15.2 binaries are x86_64 only; plan: build it once on an Apple Silicon Mac and
  snapshot it) and ad-hoc code signing (e.g. `rcodesign`). Then lipo into a universal app.
- **the frozen `osx64` channel** (Qt 5.6.3, macOS 10.7): its Qt and the 10.7 SDK are in the
  macmini snapshot, but no build is set up.
