# windows-win32: win32 toolchain (Wine)

Image `multimc/toolchains/windows-win32:dev`. Builds the `win32` Launcher on Linux under
Wine with the exact toolchain of the old Win7 build VM (snapshot `2026-10-21-win7-vm`),
replacing the VM.

    docker build -t multimc/toolchains/windows-win32:dev .

The build steps are hopper's `build/win32.sh`.

## Pieces

| Piece | What / why |
|-------|------------|
| `Dockerfile` | Minimal Arch pinned by digest, packages from the Arch Linux Archive snapshot 2026/10/20 (only `lib32-glibc` and `lib32-gcc-libs` added, for GE-Proton's 32-bit side), GE-Proton10-15, the `Tools/` subset (see `.dockerignore`), a ready-made Wine prefix (with the `libvkd3d` DLLs copied in by hand, as the prefix isn't made through Proton's launcher script). Sets `WINE`, `TOOLS`, `PREFIX_TEMPLATE` for the build steps. |
| `GE-Proton10-15/` | The Wine, run as `files/bin/wine` (the i386 launcher, classic 32/64-bit mode). Known good from the original Wine prototype; copied in as-is. Not in git. |
| `Tools/` | The VM's toolchain, hash-verified against the VM disk (see the snapshot). Not in git. The image takes `Qt/5.6.3/mingw49_32` + `Qt/Tools/mingw492_32` (Qt 5.6.3, MinGW 4.9.2), `CMake-3.20.1` (the CMake the VM built with, extracted from the VM disk), `GnuWin32` (zlib), `OpenSSL-Win32` (OpenSSL 1.0 DLLs). The rest (`QtX`: Qt 5.15.2 / 6.5.3, `CMake`: 4.1.2; and, as they can't be redistributed, `Tools/`: the VM's MSVC `dumpbin`/`link`, and `jdk1.8.0_112`: Oracle's JDK, under the Binary Code License) isn't used. |
| `dumpbin/` | Our own `dumpbin /dependents` for the bundling, built in the image with its MinGW into `Tools/Tools/dumpbin.exe` (see [its README](dumpbin/README.md)). Replaces the VM's MSVC dumpbin (2026-10-30). |
| `tarballs/` | `OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.zip`: Temurin JDK 8, the same release as the macOS image, for the Launcher's jars (`javac -target 7`). From Adoptium; SHA-256 matches the Adoptium API and the release's `.sha256.txt`, PGP signature good (Adoptium key `3B04D753C9050D9A5D343F39843C48A565F8F04B`), checked 2026-10-30; the Dockerfile checks the SHA-256 again. Installed as `Tools/jdk8`, its Windows path in `JDK` for the build steps. Not in git (`SHA256SUMS` is). Replaces the VM's Oracle JDK 8u112 (2026-10-30). |

## Verification (2026-10-21, develop 2a684511)

Against the shipped `mmc-develop-win32.zip` (`snapshots/2026-10-21-deth001/downloads`),
built by the VM from the same commit:

- same 30 files; 22 byte-identical (all Qt DLLs and plugins, MinGW runtime, OpenSSL, zlib,
  `qt.conf`)
- `libLauncher_*.dll`: code, data, imports, exports, relocations identical; only the link
  timestamp, checksum and 1–4 bytes of linker padding differ
- jars: identical classes (zip timestamps differ)
- `MultiMC.exe`: same 2611 imports, same PE headers (subsystem 4.0, so still XP), 9 KB
  smaller: embedded text resources with LF instead of CRLF line endings (the VM's git
  checkout converted them) and shorter embedded source paths. A control build with a CRLF
  checkout at the VM's path matched the shipped exe except the git refspec string (detached
  control checkout), pointers to it, padding and timestamps: the compiler output is the same.
- all 15 unit tests pass under Wine

Not covered: running it on real Windows XP.

Since 2026-10-30 the bundling uses our own dumpbin instead of the VM's MSVC one; the
builds came out identical, see [`dumpbin/README.md`](dumpbin/README.md).

Since 2026-10-30 the JDK is Temurin 8u504 instead of the VM's Oracle 8u112. Clean builds of
develop da162756 with the image before and after: the same 30 files, `MultiMC.exe` and every
DLL byte-identical, every class in both jars byte-identical; the jars' `META-INF/MANIFEST.MF`
now says `Created-By: 1.8.0_504 (Temurin)` instead of `1.8.0_112 (Oracle Corporation)`. Both
pass the compatibility gate and all 15 tests; build time unchanged (73 s).

## Notes

- Debian's Wine 8.0 was tried first and hangs CMake's Java check (`java -version` makes Wine
  start `explorer.exe /desktop`, which inherits CMake's output pipe and never exits).
  GE-Proton10-15 doesn't. Don't swap the Wine without re-verifying.
- `win32-5.15.2` (Qt 5.15.2, MinGW 8.1) is dead and not built.
