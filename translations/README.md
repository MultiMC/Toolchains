# Translation tools image

`multimc/toolchains/translations`: Qt 5.15.2 `lupdate`, `lconvert`, `lrelease` built from
source, plus gettext and python3. Used by `update.sh` / `release.sh` / `validate_po.py`
in the MultiMC5-translate repository. Replaces the Qt 5.6.3 tools from the `linux-x64`
build image for translation work.

    docker build -t multimc/toolchains/translations:dev .

Inputs in `tarballs/` (fetch from download.qt.io/archive/qt/5.15/5.15.2/submodules/,
check with `sha256sum -c tarballs/SHA256SUMS`): `qtbase-everywhere-src-5.15.2.tar.xz`,
`qttools-everywhere-src-5.15.2.tar.xz`. Base image pinned by digest. The built image is
archived as `../images/candidates/translations.tar.zst`.

The image also has what the Update Template job needs to push `template.pot`: an SSH
client, GitHub's RSA host key in `/etc/ssh/ssh_known_hosts` (`github_known_hosts`, taken
from the old `linux-x64` image and checked against https://api.github.com/meta), and
`safe.directory = *`, because TeamCity runs the container as root on a checkout owned by
the agent user and git refuses that otherwise ("dubious ownership").

## Why Qt 5.15.2 (findings, 2026-10-21)

- **Extraction**: Qt 5.6.3's `lupdate` doesn't understand C++11 raw string literals.
  At `MainWindow.cpp:1385` (`R"(...)"`, the cat background stylesheet) it stops parsing
  the file, so 17 strings after it were never translatable. Qt 5.15.2 finds those 17 and
  everything 5.6.3 finds, with the same contexts (1111 vs 1094 strings on develop
  2a684511). Linux and macOS 5.15.2 `lupdate` produce the same string set.
- **Platforms**: lupdate reads every `#ifdef` branch, and all platforms build from the
  same source, so Windows/Linux/macOS look up the same strings. Only 2 `tr()` calls sit
  in platform `#if` blocks; both are extracted. No `.mm` or other unscanned file uses
  `tr()` (`update.sh` now checks this).
- **Release**: a `.qm` from 5.15.2 `lrelease` is the 5.6.3 one plus a 5-byte language
  block (tag 0xA7). Qt 5.6.3's `QTranslator` skips it: tested by loading both versions
  in a program built against the Qt 5.6.3 from the `linux-x64` image, same results.
  The `.qm` hashes all change once, so clients re-download each language once.
- **Reproducibility**: `release.sh` on MultiMC5-translate c1e4f6ac with the old tools
  (archived `linux-x64` image) reproduces the deployed `index_v2.json` and all 56 `.qm`
  byte for byte. With the new tools the index statistics are identical.
