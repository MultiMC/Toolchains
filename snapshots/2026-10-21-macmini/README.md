# macmini.peterix.cz, 2026-10-21

Taken over SSH from the macOS build machine (Macmini7,1, macOS 11.6, Xcode 12.4).
`SHA256SUMS` covers the tarballs; `MANIFEST.txt` records the machine state (OS, Xcode, SDK
list, clang, cmake, Java, `qmake -query` for both Qts, the TeamCity agent config).

| File | Contents | Used by |
|------|----------|---------|
| `macmini-Qt.tar.zst` | `/Users/peterix/Qt`: Qt 5.15.2 `clang_64` (current channel), 5.6.3 `clang_64` (frozen `osx64` channel), the Qt installer files | `containers/macos-osx64` (Qt 5.15.2) |
| `macmini-CMake.app.tar.zst` | `/Applications/CMake.app` (CMake 3.20.0, used by the TeamCity agent) | reference |
| `xcode-12.4-sdks.tar.zst` | Xcode's macOS SDKs: 11.1 (`MacOSX.sdk`), plus 10.7 and 10.8 copied in by hand for the old 10.7-compatible builds | `containers/macos-osx64` (SDK 11.1) |
| `xcode-12.4-toolchain-libcxx-clangrt.tar.zst` | Xcode toolchain libc++ headers, clang 12 runtime libs, libarclite | `containers/macos-osx64` (libc++ headers) |

The archives were made with macOS `tar`, so they contain AppleDouble `._*` entries and
`SCHILY.fflags` headers; on Linux extract with `--exclude='._*' --warning=no-unknown-keyword`.
Paths are absolute (Qt has its install prefix compiled in).
