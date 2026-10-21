#!/bin/bash
# Build tarballs/MacOSX11.1.sdk.tar.xz for osxcross from the archived macmini Xcode 12.4.
#
# Xcode 12 keeps libc++ headers in the toolchain, not the SDK, so they are merged into
# the SDK's usr/include/c++/v1 (the same thing osxcross's gen_sdk_package.sh does on a Mac).
# Output is deterministic: sorted entries, fixed owner and mtime.

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ARCHIVE=${ARCHIVE:-$HERE/../../snapshots/2026-10-21-macmini}
OUT=$HERE/tarballs/MacOSX11.1.sdk.tar.xz

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

tar --zstd -xf "$ARCHIVE/xcode-12.4-sdks.tar.zst" --warning=no-unknown-keyword --exclude='._*'
tar --zstd -xf "$ARCHIVE/xcode-12.4-toolchain-libcxx-clangrt.tar.zst" --warning=no-unknown-keyword --exclude='._*'

X=Applications/Xcode.app/Contents/Developer
SDK=$X/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
grep -q '"Version":"11.1"' "$SDK/SDKSettings.json"

mkdir -p "$SDK/usr/include/c++"
cp -a "$X/Toolchains/XcodeDefault.xctoolchain/usr/include/c++/v1" "$SDK/usr/include/c++/"

mkdir pkg
cp -a "$SDK" pkg/MacOSX11.1.sdk
mkdir -p "$(dirname "$OUT")"
tar -C pkg --sort=name --owner=0 --group=0 --numeric-owner --mtime=2020-11-30 -cf - MacOSX11.1.sdk | xz -T1 -6 > "$OUT"
sha256sum "$OUT"
