# deth001.multimc.org, 2026-10-21

## `images/`

`docker save` of TeamCity's toolchain images `ghcr.io/multimc/toolchains/*:latest` as they
were on deth001 that day, zstd-compressed. `IMAGES.txt` has their image IDs and registry
digests there; `SHA256SUMS` covers the tarballs.

    zstd -dc toolchains-linux-x64.tar.zst | docker load

| Image | Contents | Used by |
|-------|----------|---------|
| linux-x64 | Ubuntu 14.04 amd64, glibc 2.19, g++-5.5, Qt 5.6.3 (`/opt/qt56`, beineri PPA), cmake 3.10.0, OpenJDK 8 | `containers/linux-x64` (unchanged) |
| linux-x32 | the same for i386, but cmake 3.6.0 (too old for the Launcher since it requires 3.10) | `containers/linux-x32` (adds cmake 3.10.0) |
| deployer | Ubuntu, repoman2, s3cmd, the Patreon credits script | reference for the deploy step |
| site | hugo 0.31.1 | reference for the website |
| windows | Arch + wine + a Windows tools tree (an experiment, never pushed to ghcr) | nothing |

These images are the only authoritative copies: the Dockerfiles they were made from
(in git history) don't reproduce them (Ubuntu ESM, PPAs). Don't rebuild them; load these.

## `downloads/`

The shipped packages from `/home/http/files/downloads` (files.multimc.org/downloads), that
day's develop and stable builds. The develop ones are the compatibility baselines of
`automation/compat-check.py` (setting `BASELINES`).

| Package | Built by | Facts |
|---------|----------|-------|
| `mmc-develop-lin64.tar.gz` | TeamCity, develop 2a684511 | x86-64, max GLIBC_2.14 / GLIBCXX_3.4.21 |
| `mmc-develop-lin32.tar.gz` | TeamCity, develop (June 2025) | i386, max GLIBC_2.4 / GLIBCXX_3.4.21 |
| `mmc-develop-win32.zip` | Win7 VM, develop 2a684511 | PE OS/subsystem 4.0 (XP), Qt 5.6.3, OpenSSL 1.0 |
| `mmc-develop-osx64-5.15.2.tar.gz` | macmini, develop 2a684511 | Qt 5.15.2, minimum macOS 10.13, SDK 11.1 |
| `mmc-stable-*` | 2023-02-04 | the last stable builds; `osx64` is the frozen Qt 5.6.3 / macOS 10.7 channel |
