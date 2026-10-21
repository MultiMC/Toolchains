#!/bin/bash
# Install the macmini's Qt 5.15.2 clang_64, made usable from Linux, under $QT_ROOT
# (default: work/qt; the image uses /, i.e. /Users/peterix/Qt/5.15.2/clang_64).
#
# The prebuilt macOS Qt is used as-is for headers, frameworks and plugins. Only its
# build-time tools are macOS binaries, so they are moved to bin.macos/ and replaced:
#   moc, rcc, uic -> symlinks to the Linux 5.15.2 builds in the image (/opt/qt5-host/bin)
#   qmake         -> a stand-in answering the -query calls the Launcher's CMake makes
# The tree keeps its original path (/Users/peterix/Qt/5.15.2/clang_64) and is mounted
# there by build-osx64.sh.

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ARCHIVE=${ARCHIVE:-$HERE/../2026-10-21}
W=${QT_ROOT:-$HERE/work/qt}
P=/Users/peterix/Qt/5.15.2/clang_64

# Only ever remove the Qt directory itself, never $W (which may be /).
rm -rf "${W%/}$P"
mkdir -p "${W%/}/"
tar -C "${W%/}/" --zstd -xf "$ARCHIVE/macmini-Qt.tar.zst" --warning=no-unknown-keyword \
    --exclude='._*' --exclude='.DS_Store' "${P#/}"

cd "${W%/}$P/bin"
mkdir -p ../bin.macos
for t in moc rcc uic qmake; do mv "$t" ../bin.macos/; done
for t in moc rcc uic; do ln -s "/opt/qt5-host/bin/$t" "$t"; done

cat > qmake <<EOF
#!/bin/sh
# Stand-in for the macOS qmake when cross-building on Linux: answers -query only.
P=$P
EOF
cat >> qmake <<'EOF'
case "$1 $2" in
  "-query QT_INSTALL_PLUGINS") echo $P/plugins ;;
  "-query QT_INSTALL_LIBS") echo $P/lib ;;
  "-query QT_INSTALL_LIBEXECS") echo $P/libexec ;;
  "-query QT_INSTALL_PREFIX") echo $P ;;
  "-query QT_VERSION") echo 5.15.2 ;;
  "-query QT_INSTALL_BINS") echo $P/bin ;;
  "-query QT_INSTALL_HEADERS") echo $P/include ;;
  *) echo "qmake stand-in: unsupported: $*" >&2; exit 1 ;;
esac
EOF
chmod +x qmake
echo "prepared ${W%/}$P"
