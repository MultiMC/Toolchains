# windows-win32-qt5.15

Image `multimc/toolchains/windows-win32-qt5.15:dev`. Builds the `win32-5.15.2` Launcher
(Qt 5.15.2, Windows 7 and newer) under Wine, like the old Win7 build VM's second Windows
build did. It is the [`windows-win32`](../windows-win32/README.md) image (GE-Proton10-15,
its Wine prefix, CMake 3.20.1, GnuWin32 zlib, our `dumpbin`, Temurin JDK 8) plus the VM's
second Qt, at the VM's paths (`C:\QtX` there, `$TOOLS/QtX` here):

| Path in `$TOOLS` | What |
|------------------|------|
| `QtX/5.15.2/mingw81_32` | Qt 5.15.2 for MinGW 8.1, 32-bit (Qt's build) |
| `QtX/Tools/mingw810_32` | MinGW 8.1.0, i686 (Qt's build) |
| `QtX/Tools/OpenSSL/Win_x86/bin` | Qt's OpenSSL 1.1.1j: `libcrypto-1_1.dll` and `libssl-1_1.dll` only |
| `QtX/vcredist/x86/msvcr100.dll` | the Visual C++ 2010 SP1 runtime (10.0.40219.1) that Qt's OpenSSL 1.1 needs, taken out of `QtX/vcredist/vcredist_x86.exe` (Qt's installer put it there) during the image build; both hashes are checked |

They come from `../windows-win32/Tools/QtX` (hash-verified against the VM disk, see the
snapshot `2026-10-21-win7-vm`), passed in as named build contexts so they aren't copied
twice:

    docker buildx build -t multimc/toolchains/windows-win32-qt5.15:dev \
        --build-context qt=../windows-win32/Tools/QtX/5.15.2/mingw81_32 \
        --build-context mingw=../windows-win32/Tools/QtX/Tools/mingw810_32 \
        --build-context openssl=../windows-win32/Tools/QtX/Tools/OpenSSL/Win_x86/bin \
        --build-context vcredist=../windows-win32/Tools/QtX/vcredist \
        --load .

The base is `windows-win32` as published on 2026-10-30, pinned by digest. The build steps
are hopper's `launcher/steps/win32.sh`, which picks the toolchain by platform.

## Verification (2026-11-05, develop 89b9ef41)

Against the shipped `mmc-develop-win32-5.15.2.zip` (build 4249, the last one TeamCity
built, before the channel stopped):

- every toolchain file the build bundles (Qt DLLs and plugins, MinGW runtime, OpenSSL,
  zlib, `qt.conf`) is byte-identical to 4249's
- the same files, plus `imageformats/qwebp.dll` (Launcher GH-2633, newer than 4249) and
  `msvcr100.dll` (see below)
- all 26 unit tests pass under Wine; it passes hopper's compatibility gate
  (`launcher/expectations/win32-5.15.2.toml`, made from 4249)
- built the same way on the build server, with rootless podman

Not covered: running it on real Windows.

## Notes

- Qt's OpenSSL 1.1 DLLs import `msvcr100.dll` (the Visual C++ 2010 runtime), which isn't
  part of Windows. The VM's build didn't bundle it (its "Add OpenSSL" step copied only the
  two OpenSSL DLLs), so on machines without it the Launcher had no TLS. Bundled since 2026-11-06, next to the OpenSSL DLLs (an app-local copy,
  as Microsoft's redistribution terms allow).
- The PE headers say 5.1 (XP), as MinGW 8.1 writes them, but Qt 5.15 needs Windows 7.
