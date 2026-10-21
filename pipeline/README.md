# Release pipeline

Replaces the TeamCity Launcher builds. Stage 1: build, package and verify. Nothing is
deployed yet.

    ./release-build.sh [--config FILE] [--incremental [--clean]] <build-number> <out-dir> [commit]

1. Updates a local mirror of the Launcher repo (`state/launcher.git`, git-ignored) and
   checks out `develop` as a branch at the commit (default: develop head), with
   submodules. A branch, not a detached commit, so the commit and `refs/heads/develop`
   are embedded like in the TeamCity builds. The commit must be on `develop`.
2. Builds `lin64`, `lin32`, `win32`, `osx64-5.15.2` in parallel, each in its archived
   toolchain image with no network:
   `../linux/build-linux.sh`, `../windows/build-win32-docker.sh`,
   `../macos/cross/build-osx64.sh`. Unit tests run for all but macOS (macOS binaries).
   Any failure stops the release.
3. Packages them like TeamCity's deploy did: `packages/mmc-develop-<platform>.tar.gz`
   (`.zip` for win32), with the same layout as the shipped packages.
4. Runs `compat-check.py` for each platform against `../baselines/2026-10-21`.
5. Writes `manifest.json`: commit, build number, package hashes, gate results,
   `releasable`.

Exit status 0 only if everything built and passed the gate. Takes about 2 minutes on a
32-core machine. Output files belong to the user running it.

The build number is passed in explicitly. It must keep increasing for the updater; the
last one TeamCity shipped was 4278. A counter takes over at cutover.

## Incremental builds (`--incremental`)

For development. The source checkout and one build tree per platform persist in
`state/work/` (locked, so only one incremental build runs at a time):

- the checkout is updated with git (`checkout -B`, `reset --hard`, `clean -ffdx`, same for
  submodules), so only files that actually changed get new timestamps;
- build trees are mounted at the same container paths every time, so CMake's cached paths
  stay valid; CMake configure runs on every build, so CMake changes and the embedded commit
  are always picked up; the install tree and packages are always made fresh;
- the Windows Wine prefix is kept too.

`--clean` starts the persistent trees from scratch. Without `--incremental` every build is
clean (fresh checkout and build trees in the output directory), as for releases.

Verified 2026-10-21: an incremental build of 2a684511 on top of a305dab9 (one changed
file, 34 s instead of ~2 min) produced the same binaries on all four platforms as a clean
build of 2a684511. Only the jars (zip timestamps) and `libLauncher_nbt++.dll.a` (archive
timestamps) differ. An unchanged rebuild takes ~26 s (configure, install, packaging, gate).

For that, the macOS build sets `SOURCE_DATE_EPOCH` to a fixed value: Qt 5.15's `rcc`
embeds file modification times in resources, and with the commit time an incremental
build kept the previous commit's time in resources that didn't change.

## Settings

Every setting (repo, branch, platforms, images, build type, jobs, macOS deployment target,
extra CMake arguments, the URLs compiled into the Launcher, baselines) is listed with its
default in `defaults.env`. Override with a file of the same `KEY=value` form
(`--config FILE`, or `CONFIG=FILE` for the platform scripts) or environment variables;
environment > config file > defaults. `config.sh` loads them and hands them into the
containers. Each platform script loads the same settings when run on its own.

Of the URLs, only `UPDATER_BASE` and `NOTIFICATION_URL` currently take effect: the
Launcher's `CMakeLists.txt` hard-codes the subreddit, Discord and bug tracker URLs.

## Compatibility gate (`compat-check.py`)

    compat-check.py <platform> <install tree> <baseline package> [--json out.json]

| Platform | Checks |
|----------|--------|
| all | same file list as the baseline (new or missing files fail until the baseline is updated on purpose) |
| lin64, lin32 | ELF architecture; no system library needed that the baseline didn't need; no newer `GLIBC_`/`GLIBCXX_`/`CXXABI_`/`GCC_` symbol versions (baseline: 2.14 / 2.4, 3.4.21) |
| win32 | i386 only; PE OS/subsystem version not above 4.0 (XP); no new system DLL imports; bundled third-party DLLs byte-identical to the baseline |
| osx64-5.15.2 | x86_64 only; minimum macOS not above 10.13; nothing linked from outside the bundle, `/usr/lib`, `/System` |
| all | every URL embedded in the baseline's main binary is still there (catches e.g. a missing updater URL, which would cut users off from updates) |

Verified 2026-10-21: all four builds of develop 2a684511 pass, and deliberately broken
copies fail (extra file, GLIBC_2.34 library, subsystem 6.0, modified Qt5Core.dll,
minimum macOS 10.15). The URL check was added after an early macOS cross build turned out
to lack the updater and notification URLs (never deployed); it fails that build.

Needs `objdump` and `llvm-otool` on the host.

## Requirements

Docker with the toolchain images loaded (`../images/`), git, python3, outbound access
to GitHub.
