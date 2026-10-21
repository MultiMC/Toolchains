# Windows (win32) toolchain

Builds the `win32` Launcher on Linux under Wine, with the exact toolchain of the old Win7
build VM (`buildbot_w32.qcow2`, archived in `../windows-vm/`). Replaces the VM.

## Pieces

| Piece | What / why |
|-------|------------|
| `Tools/` | The VM's toolchain (not in git; in the archives). The win32 build uses `Qt/5.6.3/mingw49_32` + `Qt/Tools/mingw492_32` (Qt 5.6.3, MinGW 4.9.2), `CMake-3.20.1`, `Tools/` (MSVC `dumpbin`/`link`, used by CMake's bundling because it is much faster than MinGW's objdump), `GnuWin32` (zlib), `OpenSSL-Win32` (OpenSSL 1.0 DLLs), `jdk1.8.0_112`. Hash-compared against the VM image on 2026-10-21: all identical except installer metadata. `Tools/QtX` (Qt 5.15.2 / 6.5.3) and `Tools/CMake` (4.1.2) are not used by the win32 build. |
| `Tools/CMake-3.20.1` | The CMake the VM actually built with (`C:\Program Files\CMake`), extracted from `../windows-vm/2026-10-21/vm-CMake-3.20.1.tar.zst`. |
| `GE-Proton10-15/` | The Wine used, run as `files/bin/wine` (the i386 launcher, classic 32/64-bit mode). Known good from the prototype; used as-is (not in git; in the archives). |
| `build-win32.sh` | The build. Mirrors the TeamCity Windows build: Release, `win-bundle` layout, MinGW Makefiles, `CMAKE_GP_TOOL=dumpbin`, tests via ctest (a failure stops the build), install, then the OpenSSL DLLs copied in. Fresh Wine prefix per build; only drives `T:` (tools), `S:` (source), `O:` (output) are mapped, nothing else of the host. Runs on a host (Wine + `Tools/` next to it) or in the image. |
| `win32.Dockerfile` | The image `multimc/toolchains/windows-win32`: minimal Arch pinned by digest, packages from the Arch Linux Archive snapshot 2026/10/20 (only `lib32-glibc` and `lib32-gcc-libs` added, for GE-Proton's 32-bit side), GE-Proton10-15, the `Tools/` subset (`win32.Dockerfile.dockerignore`), a ready-made Wine prefix (with the `libvkd3d` DLLs copied in, as in `build.sh`). |
| `build-win32-docker.sh` | Runs a build in the image, without network. |
| `build.sh`, `setup.sh`, `Dockerfile`, `WineRoot/`, `Data/` | The original prototype (debug builds, 5.15.2 experiment). Kept for reference. |

## Usage

    ./build-win32-docker.sh <Launcher checkout> <out dir> <build number>

The checkout must be on its branch (`develop`), not a detached commit, so the commit and
`refs/heads/develop` get embedded like in the TeamCity builds. Result:
`<out>/install/MultiMC`, logs in `<out>/*.log`. About 2.5 minutes.

The image is archived as `../images/candidates/windows-win32.tar.zst`
(`zstd -dc ... | docker load`). To rebuild it: `docker build -f win32.Dockerfile -t multimc/toolchains/windows-win32:dev .`
(needs `Tools/` and `GE-Proton10-15/` from the archives).

## Verification (2026-10-21, Launcher develop 2a684511)

Against the shipped `mmc-develop-win32.zip` (`../baselines/2026-10-21/`), built by the VM
from the same commit:

- same 30 files; 22 byte-identical (all Qt DLLs and plugins, MinGW runtime, OpenSSL,
  zlib, `qt.conf`)
- `libLauncher_*.dll`: code, data, imports, exports, relocations identical; only the link
  timestamp, checksum and 1–4 bytes of linker padding in `.rdata` differ
- jars: identical classes (only zip timestamps differ)
- `MultiMC.exe`: same 2611 imports, same PE headers (subsystem 4.0, so still XP), 9 KB
  smaller. That is entirely embedded text resources with LF instead of CRLF line endings
  (the VM's git checkout converted them) plus shorter embedded source paths
  (`S:\` instead of `C:\BuildAgent\work\1995660496931de4\`). Neither changes behaviour.
- Control build with a CRLF checkout at the VM's path and the same build number:
  `MultiMC.exe` then matched the shipped one except the git refspec string (control
  checkout was detached), the pointers to it, one padding byte, and timestamps. So the
  compiler output is the same.
- all 15 unit tests pass under Wine.
- the image's build is identical to a build with the host's Wine except linker padding.

Not covered: running it on real Windows XP (no XP machine available).

## Notes

- Debian's Wine 8.0 was tried first and hangs CMake's Java check: `java -version` makes
  Wine start `explorer.exe /desktop`, which inherits CMake's output pipe and never exits.
  GE-Proton10-15 doesn't have that problem. Don't swap the Wine without re-verifying.
- `win32-5.15.2` (Qt 5.15.2, MinGW 8.1) is dead and not built.
