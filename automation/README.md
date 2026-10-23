# Build automation

Replaces the TeamCity Launcher builds: build, package, verify, deploy into a local copy of
the files tree, publish to the live tree and S3. TeamCity still does the real releases.

| File | What |
|------|------|
| `release-build.py` | Builds a release of all platforms: checkout, parallel builds, packaging, compatibility gate, manifest |
| `run-build.py` | Builds one platform in its toolchain container. The same for every platform |
| `build/linux.sh`, `build/win32.sh`, `build/osx64.sh` | The build steps, run inside the containers (mounted at `/build`) |
| `compat-check.py` | The compatibility gate: compares a build with the shipped one |
| `deploy.py` | Deploys a release into the local files tree |
| `publish.py` | Publishes a deployed release to the live tree and S3 |
| `files-pull.py` | Makes the local files tree a copy of the live one |
| `common.py` | Shared by the scripts: settings, platforms, the container command, locking |
| `defaults.env` | Every setting, with its default |
| `files2.env` | Settings for the files2 test system |
| `state/` | Not in git: the Launcher repo mirror, the incremental work trees, the files trees |

## Principles

No black boxes: every part runs on its own and its results can be inspected; the pipeline
fails closed (stops and lets nothing through to users); intermediate results are
versioned, so the real system can be debugged in place and any mess undone. How this
automation measures up:

- **Runnable parts:** each step is its own script (`run-build.py`, `compat-check.py`,
  `release-build.py`, `deploy.py`, `publish.py`, `files-pull.py`); `publish.py` and
  `files-pull.py` have `--dry-run`.
- **Inspectable results:** a release directory keeps the source, build trees, logs,
  packages, deploy archives, gate reports and `manifest.json`.
- **Fails closed:** a failed build or test stops the release; the gate refuses anything
  that differs from the shipped builds; `deploy.py` refuses releases that aren't
  releasable, were built for another system, or aren't newer; `publish.py` refuses when
  the live tree changed underneath it; settings files with unknown keys are refused.
- **Not yet versioned:** `deploy.py` changes the local files tree in place, and
  `publish.py` overwrites the live indexes and downloads. Undo today is `files-pull.py`
  (only where a live tree exists; files2's local tree is its only copy), and nothing
  undoes a publish. Release directories are kept wherever they were built.

The scripts on the host are Python (3.12 or newer, standard library only). The build steps
run inside the containers are plain bash: the Windows image has no Python.

## Settings

Every setting (repo, branch, platforms, images, clean/incremental, build type, jobs, macOS
deployment target, extra CMake arguments, the URLs compiled into the Launcher, baselines,
the deployer image, the files trees, the S3 target) is listed with its default in
`defaults.env`. Every script takes `--config FILE`, a file of the same `KEY=value` form that
may only set settings from `defaults.env`; environment variables override both. Values may
be quoted and may use `$TOOLCHAINS`, `$HOME` and settings defined before them.
`common.load_settings` reads them; every setting is also passed into the build containers.

Of the URLs only `UPDATER_BASE` and `NOTIFICATION_URL` take effect: the Launcher's
`CMakeLists.txt` hard-codes the subreddit, Discord and bug tracker URLs with plain `set()`.

## Building one platform

    ./run-build.py [--config FILE] <lin64|lin32|win32|osx64-5.15.2> <source dir> <output dir> [build number]

The source must be a git checkout on its branch (not detached), with submodules, so the
commit and `refs/heads/<branch>` are embedded like in the TeamCity builds. The output
directory gets `build/` (the build tree; reused unless `CLEAN=1`), `install/` (the bundle:
`MultiMC/` or `MultiMC.app/`, always fresh) and `*.log`; win32 also keeps its Wine prefix
there.

Every platform runs the same way (`common.build_command`): its image (settings `IMAGE_*`,
built from `../containers/`), no network, as the calling user, source at `/src` read-only,
output at `/out`, `build/` at `/build` read-only, all settings plus `PLATFORM` and
`BUILD_NUMBER` in the environment, command `bash /build/<script>`. The images contain only
toolchains.

## Releases

    ./release-build.py [--config FILE] [--incremental [--clean]] <build number> <out dir> [commit]

1. Updates a local mirror of the Launcher repo (`state/launcher.git`) and checks out the
   branch (default `develop`) at the commit (default: its head), with submodules. The
   commit must be on the branch.
2. Builds every platform in `PLATFORMS` in parallel, each logging to
   `build-<platform>.log`. Unit tests run for all but macOS (macOS binaries). Any failure
   stops the release.
3. Packages them like TeamCity's deploy did: `packages/mmc-<branch>-<platform>.tar.gz`
   (`.zip` for win32), same layout as the shipped packages; and `deploy/<platform>.tar.gz`,
   the bundle with its permissions, for `deploy.py`.
4. Runs `compat-check.py` for each platform against the shipped builds (`BASELINES`).
5. Writes `manifest.json`: commit, build number, version name (`major.minor.hotfix` from
   the Launcher's `CMakeLists.txt`), mode, `UPDATER_BASE`, package hashes, gate results,
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

`--clean` starts the persistent trees from scratch; use it after a toolchain image changes,
since the CMake caches remember the old one's paths. Without `--incremental` every build is
clean (fresh checkout and build trees in the output directory), as for releases.

Verified 2026-10-21: an incremental build of 2a684511 on top of a305dab9 (one changed file;
34 s instead of ~2 min) gave the same binaries on all four platforms as a clean build of
2a684511; only the jars (zip timestamps) and `libLauncher_nbt++.dll.a` (archive timestamps)
differ. An unchanged rebuild takes ~26 s. This needed a fixed `SOURCE_DATE_EPOCH` on macOS:
Qt 5.15's `rcc` embeds file times, and with the commit time an incremental build kept an
older commit's time in resources that didn't change.

Windows: two builds with the same scripts give the same binaries, but the old MinGW linker
writes a few bytes that look like leftover memory into some tables, and those change when
the container's environment does. When the scripts moved from bash to Python (2026-10-23),
`MultiMC.exe` and `libLauncher_iconfix.dll` changed in 4 bytes each, with all 392 object
files identical.

## Compatibility gate (`compat-check.py`)

    compat-check.py <platform> <install tree> <baseline package> [--json out.json] [--url-map OLD=NEW]...

| Platform | Checks |
|----------|--------|
| all | same file list as the baseline (new or missing files fail until the baseline is updated on purpose); every URL embedded in the baseline's main binary is still there |
| lin64, lin32 | ELF architecture; no system library needed that the baseline didn't need; no newer `GLIBC_`/`GLIBCXX_`/`CXXABI_`/`GCC_` symbol versions (baseline: 2.14 / 2.4, 3.4.21) |
| win32 | i386 only; PE OS/subsystem version not above 4.0 (XP); no new system DLL imports; bundled third-party DLLs byte-identical to the baseline |
| osx64-5.15.2 | x86_64 only; minimum macOS not above 10.13; nothing linked from outside the bundle, `/usr/lib`, `/System` |

`--url-map`: the baselines embed the production URLs. A build for another system (such as
files2) is checked against the baseline URLs with the defaults of `UPDATER_BASE` and
`NOTIFICATION_URL` replaced by its own; `release-build.py` passes these when they differ.

Verified 2026-10-21: all four builds of develop 2a684511 pass; deliberately broken copies
fail (extra file, GLIBC_2.34 library, subsystem 6.0, modified Qt5Core.dll, minimum macOS
10.15). The URL check was added after an early macOS cross build turned out to lack the
updater and notification URLs (never deployed; it would have cut macOS users off from
updates); it fails that build.

Needs `objdump` and `llvm-otool` on the host.

## Deploying

    ./files-pull.py [--dry-run]                         # FILES_ROOT := exact copy of FILES_ORIGIN (deth001)
    ./deploy.py <release dir>                           # deploy a release into FILES_ROOT
    ./publish.py [--dry-run] [--no-s3] <release dir>    # publish it

### `deploy.py`

Does what TeamCity's deploy steps did on deth001, with the same repoman (`IMAGE_DEPLOYER`,
`../containers/deployer`), as the calling user, without network: for each platform
`repoman -c update push <platform> <branch> <build> <version> <bundle>/` (adds
`update/<platform>/<branch>/<build>.json`, adds it to the channel's `index.json`, copies
files the store doesn't have yet into `files/<md5>-<name>`) and
`repoman push-file downloads <package>`. The tree is locked while it runs.

It refuses a release that isn't releasable, one built for another system (the manifest's
`UPDATER_BASE` must be the tree's `update/config.json` `base_url`), and one whose build
number isn't higher than every version already in the channel.

repoman prints `Failed to load channel "main"` for every platform: `channels.json` lists a
`main` channel that has no directories. Harmless; TeamCity's deploys did the same.

Verified 2026-10-23: build 9999 of 2a684511 deployed into a fresh copy: four version files
with the same structure, keys, URLs and permissions as TeamCity's last ones (4275-4278), the
indexes extended, 41 new store files (59 MB), the four downloads replaced. Differences: win32
permissions are 0644/0755 instead of the VM's 0666/0777, and win32 gets the right version
name (TeamCity's VM builds were named `0.0.0`).

### `publish.py`

Publishes what `deploy.py` added, in an order that never lets clients see a version whose
files aren't there yet: the version's store files, the version files, the channel indexes,
the downloads.

1. Checks that each live `index.json` is the local one minus this build. If something else
   deployed meanwhile, it stops (pull and deploy again).
2. Copies those files to the live tree (`FILES_ORIGIN`, as `FILES_ORIGIN_OWNER`, mode
   `FILES_ORIGIN_MODE`; store files only if missing). Each file is replaced atomically.
3. Uploads the same files to `S3_TARGET` (`s3cmd sync --files-from`, key in `S3_CONFIG`,
   outside this repo), plus download symlinks pointing at the packages: S3 has copies of
   those (`mmc-develop-osx64.tar.gz` -> `mmc-develop-osx64-5.15.2.tar.gz`).

Publishing a release again is a no-op. Only this release's files go to S3: the
translations and Patreon jobs write to the live tree too (`translations/`, `patrons.txt`)
and upload what they change themselves; `notifications.json` is edited by hand. (TeamCity's
deploy instead synced the whole live tree to S3 from deth001, where the tree is.)

`--no-preserve`: no owner/mode metadata on the S3 objects; s3cmd still stores the MD5s it
compares by. `FILES_ORIGIN` can also be a local directory. Empty, there is no live tree:
the whole local tree is synced to `S3_TARGET` with `--delete-removed` (files2).

Verified 2026-10-23 against local stand-ins (copies of the tree for the live tree, a
scratch prefix in the files2 bucket for S3): the live stand-in ended identical to the local
tree, with mode 664; S3 got exactly the release's 104 files, including the osx64 symlink's
copy (= the new package); a second run changed nothing; a version added to the live index
meanwhile stopped it. Not yet run against deth001 or the S3 copy of files.multimc.org.

### `files-pull.py`

Overwrites the local tree (`rsync --delete`), so it also undoes local test deploys. The
first pull is ~3 GB (2 min), later ones only the changes.

## The files2 test system (`files2.env`)

A parallel system, so the whole path can be exercised without touching files.multimc.org:
`files2.multimc.org` is served directly from the Cloudflare R2 bucket `multimc-files`
(custom domain; the `r2.dev` address is off, so it is only reachable through Cloudflare).
There is no live tree: the local `state/files2` is the only copy, nothing else writes to
it, and `publish.py` just syncs it to the bucket. Builds made with `--config files2.env`
update from files2 only.

    ./release-build.py --config files2.env <build> <out>
    ./deploy.py --config files2.env <out>
    ./publish.py --config files2.env [--dry-run] <out>

Seeded 2026-10-23 from a copy of the live tree, with `update/config.json` (repoman's URLs)
and every `update/<platform>/channels.json` pointed at files2. The Launcher takes the channel
URLs from `channels.json`, so without the second part a files2 build checked
files.multimc.org for updates. Build numbers there started at 5000, clear of TeamCity's
(~4280). The key is in `S3_CONFIG` (an R2 token for that bucket). The first upload (3.2 GB)
took 40 min; a release takes ~40 s. R2 refuses s3cmd's server-side copies (files that
appear under two names); s3cmd uploads those instead.

Verified 2026-10-23: a Launcher from files2 build 5000 (lin64) offered build 5001 after it
was published, and updated itself to it.

## Requirements

Docker with the toolchain images built or loaded (`../containers/`), git, python3 (3.12+),
rsync, outbound access to GitHub.
