# Build automation

Replaces the TeamCity Launcher builds. Stage 1: build, package and verify. Nothing is
deployed yet.

| File | What |
|------|------|
| `release-build.sh` | Builds a release of all platforms: checkout, parallel builds, packaging, compatibility gate, manifest |
| `run-build.sh` | Builds one platform in its toolchain container. The same for every platform |
| `build/linux.sh`, `build/win32.sh`, `build/osx64.sh` | The build steps, run inside the containers (mounted at `/build`) |
| `compat-check.py` | The compatibility gate: compares a build with the shipped one |
| `defaults.env`, `config.sh` | Settings and their loader |
| `state/` | Not in git: the Launcher repo mirror, the incremental work trees |

## Building one platform

    ./run-build.sh <lin64|lin32|win32|osx64-5.15.2> <source dir> <output dir> [build number]

The source must be a git checkout on its branch (not detached), with submodules, so the
commit and `refs/heads/<branch>` are embedded like in the TeamCity builds. The output
directory gets `build/` (the build tree; reused unless `CLEAN=1`), `install/` (the bundle:
`MultiMC/` or `MultiMC.app/`, always fresh) and `*.log`; win32 also keeps its Wine prefix
there.

Every platform runs the same way: its image (settings `IMAGE_*`, built from
`../containers/`), no network, as the calling user, source at `/src` read-only, output at
`/out`, `build/` at `/build` read-only, all settings plus `PLATFORM` and `BUILD_NUMBER` in
the environment, command `bash /build/<script>`. The images contain only toolchains.

## Releases

    ./release-build.sh [--config FILE] [--incremental [--clean]] <build-number> <out-dir> [commit]

1. Updates a local mirror of the Launcher repo (`state/launcher.git`) and checks out the
   branch (default `develop`) at the commit (default: its head), with submodules. The
   commit must be on the branch.
2. Builds every platform in `PLATFORMS` in parallel with `run-build.sh`. Unit tests run for
   all but macOS (macOS binaries). Any failure stops the release.
3. Packages them like TeamCity's deploy did: `packages/mmc-<branch>-<platform>.tar.gz`
   (`.zip` for win32), same layout as the shipped packages.
4. Runs `compat-check.py` for each platform against the shipped builds (`BASELINES`).
5. Writes `manifest.json`: commit, build number, mode, package hashes, gate results,
   `releasable`.

Exit status 0 only if everything built and passed the gate. About 2 minutes for a clean
build on a 32-core machine. Output files belong to the user running it.

The build number is passed explicitly. It must keep increasing for the updater; the last
one TeamCity shipped was 4278. A counter takes over at cutover.

### Incremental builds (`--incremental`)

For development. The source checkout and one build tree per platform persist in
`state/work/` (locked, so one incremental build at a time):

- the checkout is updated with git (`checkout -B`, `reset --hard`, `clean -ffdx`, same for
  submodules), so only files that actually changed get new timestamps;
- build trees are mounted at the same container paths every time, so CMake's cached paths
  stay valid; CMake configure runs on every build, so CMake changes and the embedded commit
  are always picked up; install trees and packages are always made fresh;
- the Windows Wine prefix is kept too.

`--clean` starts the persistent trees from scratch. Without `--incremental` every build is
clean (fresh checkout and build trees in the output directory), as for releases.

Verified 2026-10-21: an incremental build of 2a684511 on top of a305dab9 (one changed file;
34 s instead of ~2 min) gave the same binaries on all four platforms as a clean build of
2a684511; only the jars (zip timestamps) and `libLauncher_nbt++.dll.a` (archive timestamps)
differ. An unchanged rebuild takes ~26 s. This needed a fixed `SOURCE_DATE_EPOCH` on macOS:
Qt 5.15's `rcc` embeds file times, and with the commit time an incremental build kept an
older commit's time in resources that didn't change.

## Settings

Every setting (repo, branch, platforms, images, clean/incremental, build type, jobs, macOS
deployment target, extra CMake arguments, the URLs compiled into the Launcher, baselines)
is listed with its default in `defaults.env`. Override with a file of the same `KEY=value`
form (`--config FILE`, or `CONFIG=FILE` for `run-build.sh`) or environment variables;
environment > config file > defaults. `config.sh` loads them and passes them into the
containers.

Of the URLs only `UPDATER_BASE` and `NOTIFICATION_URL` take effect: the Launcher's
`CMakeLists.txt` hard-codes the subreddit, Discord and bug tracker URLs with plain `set()`.

## Compatibility gate (`compat-check.py`)

    compat-check.py <platform> <install tree> <baseline package> [--json out.json]

| Platform | Checks |
|----------|--------|
| all | same file list as the baseline (new or missing files fail until the baseline is updated on purpose); every URL embedded in the baseline's main binary is still there |
| lin64, lin32 | ELF architecture; no system library needed that the baseline didn't need; no newer `GLIBC_`/`GLIBCXX_`/`CXXABI_`/`GCC_` symbol versions (baseline: 2.14 / 2.4, 3.4.21) |
| win32 | i386 only; PE OS/subsystem version not above 4.0 (XP); no new system DLL imports; bundled third-party DLLs byte-identical to the baseline |
| osx64-5.15.2 | x86_64 only; minimum macOS not above 10.13; nothing linked from outside the bundle, `/usr/lib`, `/System` |

Verified 2026-10-21: all four builds of develop 2a684511 pass; deliberately broken copies
fail (extra file, GLIBC_2.34 library, subsystem 6.0, modified Qt5Core.dll, minimum macOS
10.15). The URL check was added after an early macOS cross build turned out to lack the
updater and notification URLs (never deployed; it would have cut macOS users off from
updates); it fails that build.

Needs `objdump` and `llvm-otool` on the host.

## Requirements

Docker with the toolchain images built or loaded (`../containers/`), git, python3, outbound
access to GitHub.
