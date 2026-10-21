# windows-win32: win32 toolchain (Wine)

Image `multimc/toolchains/windows-win32:dev`. Builds the `win32` Launcher on Linux under
Wine with the exact toolchain of the old Win7 build VM (snapshot `2026-10-21-win7-vm`),
replacing the VM.

    docker build -t multimc/toolchains/windows-win32:dev .

The build steps are `../../automation/build/win32.sh`.

## Pieces

| Piece | What / why |
|-------|------------|
| `Dockerfile` | Minimal Arch pinned by digest, packages from the Arch Linux Archive snapshot 2026/10/20 (only `lib32-glibc` and `lib32-gcc-libs` added, for GE-Proton's 32-bit side), GE-Proton10-15, the `Tools/` subset (see `.dockerignore`), a ready-made Wine prefix (with the `libvkd3d` DLLs copied in by hand, as the prefix isn't made through Proton's launcher script). Sets `WINE`, `TOOLS`, `PREFIX_TEMPLATE` for the build steps. |
| `GE-Proton10-15/` | The Wine, run as `files/bin/wine` (the i386 launcher, classic 32/64-bit mode). Known good from the original Wine prototype; copied in as-is. Not in git. |
| `Tools/` | The VM's toolchain, hash-verified against the VM disk (see the snapshot). Not in git. The image takes `Qt/5.6.3/mingw49_32` + `Qt/Tools/mingw492_32` (Qt 5.6.3, MinGW 4.9.2), `CMake-3.20.1` (the CMake the VM built with, extracted from the VM disk), `Tools/` (MSVC `dumpbin`/`link`, used for bundling because it is much faster than MinGW's objdump), `GnuWin32` (zlib), `OpenSSL-Win32` (OpenSSL 1.0 DLLs), `jdk1.8.0_112`. The rest (`QtX`: Qt 5.15.2 / 6.5.3, `CMake`: 4.1.2) isn't used. |

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

## Notes

- Debian's Wine 8.0 was tried first and hangs CMake's Java check (`java -version` makes Wine
  start `explorer.exe /desktop`, which inherits CMake's output pipe and never exits).
  GE-Proton10-15 doesn't. Don't swap the Wine without re-verifying.
- `win32-5.15.2` (Qt 5.15.2, MinGW 8.1) is dead and not built.
