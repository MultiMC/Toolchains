# Build automation

Replaces the TeamCity Launcher builds: build, package, verify, deploy into a local copy of
the files tree, publish to the live tree and a bucket. TeamCity still does the real releases.

| File | What |
|------|------|
| `release-build.py` | Builds a release of all platforms: checkout, parallel builds, packaging, compatibility gate, manifest |
| `run-build.py` | Builds one platform in its toolchain container. The same for every platform |
| `build/linux.sh`, `build/win32.sh`, `build/osx64.sh` | The build steps, run inside the containers (mounted at `/build`) |
| `compat-check.py` | The compatibility gate: checks a build against its description (`expectations/`) |
| `translations-build.py` | Builds a translations release (the Translations repo's `release.py`, in its image) |
| `translations-template.py` | Updates the translations template from the Launcher source and pushes it |
| `patrons-update.py` | Makes the Patreon credits (`patrons.txt`) as a release |
| `deploy.py` | Deploys a release (Launcher build, translations, Patreon credits) into the local files tree |
| `publish.py` | Publishes everything that changed in the tree since the last publish to the live tree and the bucket, purges Cloudflare's cache |
| `files-pull.py` | Makes the local files tree a copy of the live one |
| `hopper.py` | hopper: watches the branch and moves each new commit through build, deploy and publish; later also tags and the UI backend |
| `releases.py` | Lists the releases in `RELEASES_DIR`; cleans up old ones (trims build trees, removes the oldest) |
| `files-snapshots.py` | Lists, takes, restores and removes snapshots of the local files tree |
| `remote/hopper-ssh` | Installed on the files host (deth001): the only things the automation's SSH key may do there |
| `common.py` | Shared by the scripts: settings, platforms, the container command, locking |
| `defaults.env` | Every setting, with its default |
| `files2.env` | Settings for the files2 test system |
| `production.env` | Settings for production: none, `defaults.env` as it is; there so every setup has a name |
| `systemd/hopper@.service` | The systemd user unit that keeps hopper running on mikoshi, one instance per settings file |
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
  its description (`expectations/`) doesn't allow; `deploy.py` refuses releases that aren't
  releasable, were built for another system, or aren't newer; `publish.py` refuses when
  the live tree changed underneath it; settings files with unknown keys are refused.
- **Versioned locally:** the local files trees are btrfs subvolumes, snapshotted before
  every change (`deploy.py`, `files-pull.py`); any earlier state can be inspected or
  restored with `files-snapshots.py`.
- **Not yet versioned:** `publish.py` overwrites the live indexes and downloads, and
  nothing undoes a publish (restoring a snapshot and publishing again only adds files).
  Releases are kept in `RELEASES_DIR/<build number>` (nothing prunes them yet).

The scripts on the host are Python (3.12 or newer, standard library only). The build steps
run inside the containers are plain bash: the Windows image has no Python.

## Settings

Every setting (repo, branch, platforms, images, clean/incremental, build type, jobs, macOS
deployment target, extra CMake arguments, the URLs compiled into the Launcher, the gate's descriptions,
the deployer image, the files trees, the bucket) is listed with its default in
`defaults.env`. Every script takes `--config FILE`, a file of the same `KEY=value` form that
may only set settings from `defaults.env`; environment variables override both. Values may
be quoted and may use `$TOOLCHAINS`, `$HOME` and settings defined before them.
`common.load_settings` reads them; every setting is also passed into the build containers.

Of the URLs only `UPDATER_BASE`, `NOTIFICATION_URL` and `TRANSLATIONS_BASE_URL` take
effect: the Launcher's `CMakeLists.txt` hard-codes the subreddit, Discord and bug tracker
URLs with plain `set()`. `TRANSLATIONS_BASE_URL` needs a Launcher with the
`Launcher_TRANSLATIONS_BASE_URL` option (branch `translations-url`, 2026-10-24); older ones
have the production URL hard-coded and ignore it. The compatibility gate only maps a URL
setting to the build's own value when the Launcher being built has the option.

**Container engine:** `CONTAINER_ENGINE` is `docker` (default; containers run as the
calling user with `-u`) or `podman` (rootless, with `--userns=keep-id`, so the calling user
is the same user inside and owns what the containers write). Everything that starts a
container goes through `common.container_run`. mikoshi uses Podman: its automation user
has no Docker access, since the `docker` group is equivalent to root.

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

    ./release-build.py [--config FILE] [--incremental [--clean]] [--build-number N] [--out DIR] [commit]

The release goes into `RELEASES_DIR/<build number>` (`state/releases/`, files2:
`state/releases-files2/`), so a plain `./release-build.py` works every time unless it hits
a real problem (a failure, another build running). A test build reusing a number
(`--build-number`) gets `<number>.2`, `.3`, ...; nothing is overwritten. `--out DIR` puts it
elsewhere; DIR must be new or empty.

1. Updates a local mirror of the Launcher repo (`state/launcher.git`) and checks out the
   branch (default `develop`) at the commit (default: its head), with submodules. The
   commit must be on the branch.
2. Builds every platform in `PLATFORMS` in parallel, each logging to
   `build-<platform>.log`. Unit tests run for all but macOS (macOS binaries). Any failure
   stops the release.
3. Packages them like TeamCity's deploy did: `packages/mmc-<branch>-<platform>.tar.gz`
   (`.zip` for win32), same layout as the shipped packages; and `deploy/<platform>.tar.gz`,
   the bundle with its permissions, for `deploy.py`.
4. Runs `compat-check.py` for each platform against its description (`GATE_DESCRIPTIONS`).
5. Writes `manifest.json`: commit, build number, version name (`major.minor.hotfix` from
   the Launcher's `CMakeLists.txt`), mode, `UPDATER_BASE`, package hashes, gate results,
   `releasable`.

Exit status 0 only if everything built and passed the gate. About 2 minutes for a clean
build on a 32-core machine. Output files belong to the user running it.

### Build numbers

The build number must keep increasing for the updater. `BUILD_COUNTER` is a file holding
the last number used; without `--build-number`, `release-build.py` takes the next one and
records it, but only once nothing can stop the build before it starts: the commit is on the
branch, the toolchain images and the gate's descriptions are there, and the source is checked out
(prepared in `RELEASES_DIR/.preparing-<pid>`, renamed to the build number after). A typo in
a commit, a missing image or a failed checkout leaves the counter alone; a build that fails
after that uses up its number, so no number is handed out twice. `--build-number N` (test builds, such as 9999) leaves the counter alone.
The counter isn't created automatically: a missing one stops the build.

- Production (`state/build-number`): not seeded yet. At cutover, seed it with the highest
  of TeamCity's last build number and every version ID already in the channels (4278 on
  2026-10-23), so builds continue above both.
- files2 (`state/build-number-files2`): seeded with 5002, its own numbering.

Standard output gets exactly one line, the release directory, as soon as it exists (also if
the build fails later); all logging goes to standard error. So
`./deploy.py "$(./release-build.py)"` works.

### Cleanup (`releases.py`)

    ./releases.py [--config FILE] list
    ./releases.py [--config FILE] cleanup [--dry-run]

A Launcher release is ~1.2 GB, almost all of it `build/` (the compiler trees; win32 alone
~750 MB). deploy.py only needs `packages/` and `deploy/`, so the cleanup first trims:
Launcher releases older than the newest `RELEASES_KEEP_BUILD_TREES` (3) lose `build/` and
`src/`, keeping packages, deploy archives, logs, compat reports and the manifest (~70 MB; a
`TRIMMED` file says when). They can still be inspected and deployed again. Of each kind
(launcher, translations, patrons, template) only the newest `RELEASES_KEEP` (30) are kept
at all. Nothing younger than `RELEASES_MIN_AGE_HOURS` (24) is touched; leftovers of
interrupted builds (`.preparing-*`) go once they are older. It takes the release lock (and
skips the run if a build holds it). hopper runs it after every publish.

### One at a time

One release build runs at a time, in any mode: they share the Launcher mirror and the
build counter, and each uses every CPU anyway. Builds into a platform's output directory
are locked too (`run-build.py` and `release-build.py` alike). `deploy.py`, `publish.py`,
`files-pull.py` and `files-snapshots.py` lock the files tree they work on. A second run
stops with an error naming the lock; locks go away with the process, however it ends.

### Stopping

SIGTERM (what a service manager sends) and Ctrl-C stop a release build cleanly: it stops its
platform builds and exits. Every container runs with `docker run --init`: as process 1 the
build script would ignore SIGTERM (Wine kept the Windows container alive), the init process
passes it on and ends the container with it. Verified 2026-10-24: a release build stopped
mid-build exits within a second and leaves no containers. `--init` changes nothing in the
output (a build with and without it: same objects, same binaries apart from the known
timestamps and the win32 linker bytes, see below).

### Incremental builds (`--incremental`)

For development. The source checkout and one build tree per platform persist in
`state/work/` (locked like every release build):

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

    compat-check.py check <platform> <install tree> <description.toml> [--json out.json] [--set NAME=VALUE]...
    compat-check.py describe <platform> <install tree or package> [--source NAME]

The gate checks each build against a description of what it must be:
`expectations/<platform>.toml`, edited by hand. When the Launcher changes on purpose (a new
file, a new system library, a URL it no longer embeds), the description is changed with it,
with a comment saying why; so every change to the gate's conditions is deliberate and
reviewed. `describe` writes a description from an existing build; it was used once
(2026-10-25), on the builds TeamCity shipped, and is there to start over from.

| Section | Checks |
|---------|--------|
| `[files]` | exactly the listed files in the bundle |
| `[urls]` | the listed URLs are embedded in the main binary; `${NAME}` is a setting (`UPDATER_BASE`, `NOTIFICATION_URL`, `TRANSLATIONS_BASE_URL`) |
| `[elf]` (lin64, lin32) | ELF architecture; only the listed system libraries; no symbol versions newer than listed (`GLIBC_2.14`, `GLIBCXX_3.4.21`, ...) |
| `[pe]` (win32) | i386 only; PE OS/subsystem version at most 4.0 (XP); only the listed system DLLs; the bundled toolchain files (Qt, MinGW runtime, OpenSSL, zlib) byte-identical (SHA-256s) |
| `[macho]` (osx64-5.15.2) | x86_64 only; minimum macOS at most 10.13; nothing linked from outside the bundle, `/usr/lib`, `/System` |

`release-build.py` passes each URL setting with `--set`: the build's own value if the
Launcher being built has the matching `Launcher_<setting>` CMake option, otherwise the
production default (such a Launcher has it hard-coded). So files2 builds are checked
against files2's URLs.

Edits so far: `${TRANSLATIONS_BASE_URL}index_v2.json` is no longer required (2026-10-25):
with `Launcher_TRANSLATIONS_BASE_URL` (branch `translations-url`) the Launcher builds the
index URL at runtime.

Verified 2026-10-25: develop 2a684511 passes on all four platforms, with production's and
files2's settings; an extra file and a modified `Qt5Core.dll` fail; the `translations-url`
branch failed on exactly the index URL until that requirement was removed. (Earlier, with
the gate comparing against the shipped binaries, deliberately broken copies failed too:
GLIBC_2.34 library, subsystem 6.0, minimum macOS 10.15. The URL check was added after an
early macOS cross build turned out to lack the updater and notification URLs; never
deployed, it would have cut macOS users off from updates.)

Needs `objdump` and `llvm-otool` on the host.

## Deploying

    ./files-pull.py [--dry-run]                         # FILES_ROOT := exact copy of FILES_ORIGIN (deth001)
    ./deploy.py <release dir>                           # deploy a release into FILES_ROOT
    ./publish.py [--dry-run] [--no-bucket] [--no-purge] # publish what changed since the last publish

Three kinds of release go into the tree: Launcher builds (`release-build.py`), translations
(`translations-build.py`) and the Patreon credits (`patrons-update.py`). Deploying changes
the local tree; publishing makes the live site match it.

### `deploy.py`

Snapshots the tree (to undo it: `files-snapshots.py restore`), then changes it. Nothing
is published; the tree is locked while it runs.

**Launcher builds:** does what TeamCity's deploy steps did on deth001, with the same
repoman (`IMAGE_DEPLOYER`, `../containers/deployer`), as the calling user, without
network: for each platform `repoman -c update push <platform> <branch> <build> <version>
<bundle>/` (adds `update/<platform>/<branch>/<build>.json`, adds it to the channel's
`index.json`, copies files the store doesn't have yet into `files/<md5>-<name>`) and
`repoman push-file downloads <package>`. Refuses a build made for another system (the
manifest's `UPDATER_BASE` must be the tree's `update/config.json` `base_url`) and one whose
build number isn't higher than every version already in the channel.

repoman prints `Failed to load channel "main"` for every platform: `channels.json` lists a
`main` channel that has no directories. Harmless; TeamCity's deploys did the same.

**Translations:** `translations/` becomes the release's files, plus the files of languages
that kept their previous release (still named in the new index); everything else in there
is removed, so nothing piles up.

**Patreon credits:** `patrons.txt` replaces the tree's.

Verified 2026-10-23: Launcher build 9999 of 2a684511 deployed into a fresh copy: four
version files with the same structure, keys, URLs and permissions as TeamCity's last ones
(4275-4278), the indexes extended, 41 new store files (59 MB), the four downloads replaced.
Differences: win32 permissions are 0644/0755 instead of the VM's 0666/0777, and win32 gets
the right version name (TeamCity's VM builds were named `0.0.0`).

### `publish.py`

Publishes the tree, not a release: what was last published is a snapshot, named in
`FILES_ROOT.published`, and the difference between it and the tree now is what goes out,
whatever deploys made it (one or several), with each file's SHA-256 then and now. (A
snapshot keeps inode numbers, so only files whose inode, size or time differ are hashed.)
A successful publish records a new snapshot as published; `files-pull.py` records the
pulled tree, which equals the live one. Restoring an earlier snapshot and publishing puts
the live site back to it.

1. **The live tree** (`FILES_ORIGIN`): every changed file must be either its published or
   its new version. Anything else means someone else changed it, and it stops (pull and
   deploy again). Accepting the new version keeps publishing again, or after an
   interruption, working: already published files are reported and skipped.
2. **Copies** the files there (as `FILES_ORIGIN_OWNER`, mode `FILES_ORIGIN_MODE`, each
   replaced atomically) in an order that never lets clients see an index whose files
   aren't there yet: store files, translation files, version files, indexes, downloads,
   anything else; removals last.
3. **The bucket** (`BUCKET_TARGET`, an rclone `remote:path`; the rclone config with its key
   is `BUCKET_CONFIG`, outside this repo) gets the same changes and removals, plus the
   download symlinks pointing at changed packages: the bucket has copies of those
   (`mmc-develop-osx64.tar.gz` -> `mmc-develop-osx64-5.15.2.tar.gz`).
4. **Purges** every changed or removed file (and those symlinks) from Cloudflare's cache at
   `PUBLIC_URL`. It needs `CLOUDFLARE_ZONE_ID` and an API token with Zone / Cache Purge
   permission in the file `CLOUDFLARE_TOKEN` (outside this repo). Up to 100 URLs per
   request (Free plan). If it fails, publishing again retries it (nothing is recorded as
   published until everything succeeded). Files changed by hand
   (e.g. a `channels.json`) aren't purged by this; purge them in the dashboard.

Without the bucket or purge settings `publish.py` refuses to start; `--no-bucket` and
`--no-purge` skip them deliberately. Production's bucket is the R2 bucket `multimc-files`
(served at `files-r2.multimc.org`), replacing Amazon S3; files2's is `multimc-files2`
(`files2-r2.multimc.org`). Both were seeded on 2026-10-24 (files2: 3.2 GB in 98 s;
production: synced from the deth001 tree it had held files2's data before). Until cutover
TeamCity keeps releasing to deth001 and S3, so the production bucket falls behind; re-sync
it then (`rclone sync` of `state/files` after `files-pull.py`). The Patreon job doesn't
write to it yet either. `notifications.json` is edited by hand. (TeamCity's deploy instead
synced the whole live tree to S3 from deth001, where the tree is.) `FILES_ORIGIN` can also
be a local directory. Empty, there is no live tree: the whole local tree is synced to the
bucket, deleting what the tree no longer has.

The bucket is written with rclone (in the deployer image): 32 transfers and checks at once,
comparing by size and MD5 (`--checksum`), so objects uploaded earlier, also by s3cmd,
aren't uploaded again. Measured 2026-10-24 on files2: 605 files, 0.96 GB in 10 s (s3cmd,
one file at a time, had needed 40 min for the 3.2 GB seed); a release's bucket steps take
~8 s instead of ~25 s. s3cmd is no longer used.

Verified:
- 2026-10-23, against local stand-ins (copies of the tree for the live tree, a scratch
  prefix in the files2 bucket): the live stand-in ended identical to the local tree, with
  mode 664; the bucket got exactly the release's 104 files, including the osx64 symlink's
  copy (= the new package); a second run changed nothing; a version added to the live
  index meanwhile stopped it.
- 2026-10-24, the purge on files2: the lin64 download was in Cloudflare's cache (`HIT`,
  build 5002's); after publishing 5005 the next request was a `MISS` that returned 5005's
  package, and the one after a `HIT` again.
- 2026-10-24, the full production path on files2 (deth001 + R2 + purge): builds 5011 (with
  s3cmd) and 5012 (with rclone, through hopper); afterwards the bucket matched the local
  tree exactly (`rclone check`, 9774 files). Not yet run for files.multimc.org.
- 2026-10-25, on files2: build 5013 (through hopper, 26 files: only what changed; before,
  every publish handled all the release's ~100 files); afterwards deth001 and the bucket
  matched the local tree; publishing again found everything already published; a live
  download changed by hand stopped it before anything was copied. Then the first
  translations release (the
  staged `release.py`, from a local test commit): 1 index changed, 1698 files removed
  (`.class`, and the unlisted `ach.qm`, `en.qm`, `pt.qm`), 16 s; files2 serves 56
  languages as `<lang>.qm`, all sizes and SHA-1s matching the index.
- 2026-10-25, publishing the tree since the last publish (replacing per-release publish
  lists, after a Patreon list deployed but not published was then skipped by the next,
  identical one): two Launcher builds deployed one after the other (5014, 5015) went out
  in one publish (26 files, both in the channel); publishing again found nothing.

Caching on files2 (2026-10-24): `files/*` has a Page Rule "Cache Everything" (store files
never change, so the cache can't go stale); `downloads/` archives are cached by Cloudflare's
defaults (4 h) and kept fresh by the purge; `update/` (indexes, version files) isn't cached,
so Launchers always see the current channel.

### Snapshots (`files-snapshots.py`)

    ./files-snapshots.py list | create <label> | restore <snapshot> | remove <snapshot>... | cleanup [--dry-run] | init

Each files tree (`FILES_ROOT`) is a btrfs subvolume. Read-only snapshots of it are kept
next to it, in `FILES_ROOT.snapshots/<time>-<label>`; `deploy.py` (`before-deploy-<build>`)
and `files-pull.py` (`before-pull`) take one before every change and refuse a tree that
isn't a subvolume. Snapshots share unchanged data with the tree, so each costs roughly what
changed after it (a release: ~100 MB). They're plain directories: `diff -r` a snapshot
against the tree to see what a deploy did.

`restore` takes a snapshot of the current state first (`before-restore`), so a restore can
be undone too, then makes the tree match the snapshot (`rsync --delete --checksum`). It
changes only the local tree. `remove` works without root (btrfs only lets the owner delete
a subvolume once it's writable and empty, which `remove` does). `init` turns an existing
directory into a subvolume: reflink copy, compare, swap; the old directory stays as
`FILES_ROOT.pre-subvolume` to delete by hand.

Every snapshot has its metadata next to it, `<snapshot>.json`: when, what kind (deploy,
published, pulled, before-pull, before-restore, init, manual) and what about (the release,
the number of files published); `list` shows them. Snapshots from before metadata get their
kind from their names.

**Cleanup** (after every publish, or `files-snapshots.py cleanup [--dry-run]`), like
snapper's number cleanup on this workstation (which snap-pac runs around every pacman
transaction; borrowed as an idea, not used, to avoid the dependency and its root daemon):
keep the snapshot recorded as published, the newest `SNAPSHOTS_KEEP_PUBLISHED` (15)
published or pulled ones (states that were live: kept longer, also for binary diffs between
releases one day), the newest `SNAPSHOTS_KEEP` (30) others, and anything younger than
`SNAPSHOTS_MIN_AGE_HOURS` (24); remove the rest.

Verified 2026-10-23 on a copy of the tree: a deploy's snapshot showed exactly what it
changed, restoring it gave back the original tree byte for byte, and deploying again
worked. `state/files` and `state/files2` were converted with `init` the same day.

### Access to the files host (`remote/hopper-ssh`)

On mikoshi the automation reaches deth001 with its own key (`hopper@mikoshi`), which root's
`authorized_keys` there ties to `/usr/local/bin/hopper-ssh` (`restrict,command=...`). The
wrapper allows only `hopper-ssh hash <tree>` (SHA-256 of listed files; the live check),
`hopper-ssh remove <tree>` (removals when publishing) and rsync's server side, all inside
`/home/http/files` and `/home/http/files2`; anything else is refused and logged
(`journalctl -t hopper-ssh`). `publish.py` uses the same commands with any key, so
publishing from the workstation (root's key) goes through the wrapper too. Verified
2026-10-25: hash, rsync pull and push work; arbitrary commands, other directories, `..`
paths and rsync elsewhere are refused.

### `files-pull.py`

Overwrites the local tree (`rsync --delete`), so it also undoes local test deploys. The
first pull is ~3 GB (2 min), later ones only the changes.

## The files2 test system (`files2.env`)

A parallel system set up like production, so the whole path can be exercised without
touching files.multimc.org. Since 2026-10-24 deth001 serves the live tree
(`/home/http/files2`, Caddy site `files2.multimc.org` next to `files`, see deth001-config),
and the Cloudflare R2 bucket `multimc-files` holds a copy, as production's bucket will; it can serve files2 as a fallback through its custom domain (the `r2.dev`
address is off). `state/files2` is the local working tree, nothing else writes to files2.
Builds made with `--config files2.env` update from files2 only.

Moving files2 onto deth001 (2026-10-24): the production tree was copied on the server,
rsync then made it identical to `state/files2` (131 files, 219 MB); build 5011 was then
published through the full production path (live-index check, copy to deth001, upload to
R2, purge), 39 s.

    ./release-build.py --config files2.env
    ./deploy.py --config files2.env state/releases-files2/<build>
    ./publish.py --config files2.env [--dry-run] state/releases-files2/<build>

Seeded 2026-10-23 (as R2 only) from a copy of the live tree, with `update/config.json` (repoman's URLs)
and every `update/<platform>/channels.json` pointed at files2. The Launcher takes the channel
URLs from `channels.json`, so without the second part a files2 build checked
files.multimc.org for updates. Build numbers there started at 5000, clear of TeamCity's
(~4280). Its bucket is `multimc-files2` since 2026-10-24 (before that, files2 used
`multimc-files`, now production's). The R2 key in `BUCKET_CONFIG` covers both buckets.

Verified 2026-10-23: a Launcher from files2 build 5000 (lin64) offered build 5001 after it
was published, and updated itself to it. Then Launchers from build 5001 on Windows 11,
macOS 11 (macmini) and Linux (lin64) all updated themselves to 5002, the first real runs
of the cross-built Windows and macOS Launchers (they also start, log in and launch the
game). lin32 is not tested yet.

## Translations (`translations-build.py`)

    ./translations-build.py [--config FILE] [--out DIR] [commit]

Mirrors `TRANSLATIONS_REPO` (`state/translations.git`), checks out `TRANSLATIONS_BRANCH`
at the commit (default: its head) and runs the repo's `release.py` in
`IMAGE_TRANSLATIONS`, without network. A language whose `.po` can't be used keeps its
previous release, taken from the local files tree's `translations/index_v2.json`. The
release goes into `RELEASES_DIR/translations-<time>-<commit>` with a manifest (kind
`translations`); `deploy.py` and `publish.py` handle it like a Launcher build. One release
build at a time, shared with `release-build.py`. Translations releases have fixed names
(`<lang>.qm`); the first one removes the `<sha1>.class` files that piled up before.

### The template (`translations-template.py`)

    ./translations-template.py [--config FILE] [--dry-run] [launcher commit]

Run by hand, as TeamCity's "Update Template" job was. Checks out the Translations repo's
`TRANSLATIONS_BRANCH` with the Launcher (default: the head of `LAUNCHER_BRANCH`, with
submodules) in its `src/`, in `RELEASES_DIR/template-<time>/`; runs the repo's `update.py`
in `IMAGE_TRANSLATIONS` without network; if `template.pot` changed, commits it ("Update
translation template for latest MultiMC code") and pushes it to `TRANSLATIONS_PUSH_URL`
with the deploy key `TRANSLATIONS_DEPLOY_KEY` (outside this repo; GitHub's host key must
already be known). If the branch moved meanwhile the push fails and nothing changes; run it
again. `--dry-run` stops before the push. Crowdin picks the template up from the repo.

Verified 2026-10-25 (dry run, Launcher e073ab64): 1111 strings, none added or removed, in
3 s; the commit only reorders entries and the source locations within four of them, the
one-time effect of `update.py` handing files to `lupdate` in sorted order.

## Patreon credits (`patrons-update.py`)

    ./patrons-update.py [--config FILE]

`patrons.txt` (the Launcher's credits) lists the active patrons of the tier in
`tokens.cfg` (`[Config] reward`, the "Patron" tier) by name, then "And N others who wish to
remain anonymous." for active patrons without a tier; `patrons.json` adds image and
Patreon URLs. Made with Patreon's API v2, plain HTTP. Then `deploy.py` and `publish.py`, as
for any release (only `patrons.txt` goes live, as before). hopper runs all three on
`PATRONS_SCHEDULE` (default `0 12 * * *`, daily at noon).

- **The token** is `PATRONS_CONFIG/tokens.cfg` (`~/.config/multimc-deploy/patreon/`, mode
  600): the API client and a refresh token. Every run refreshes it first; Patreon then
  issues a new refresh token and the old one stops working, so the new pair is saved
  (atomically, the old file kept as `tokens.cfg.prev`) before anything else is asked.
  It exists on one machine only; `files2.env` sets `PATRONS_CONFIG` empty, so files2 never
  runs it. One run at a time.
- **Checked before release:** an empty list, or one less than half as long as the live
  one, is refused, and the old list stays live.

History: TeamCity ran `patronupdater.py` (the deployer image) daily. Patreon switched off
API v1 on 2026-10-08 (410 Gone); the job kept "passing" because its step script had no
`set -e` and ended with `cat out/patrons.txt`, a file left by the last good run, which was
then re-published every day. On 2026-10-25 the API client was switched to v2 with new
tokens; the first v2 list had 19 patrons (17 unchanged, 2 new, 1 gone) and the same 6
anonymous.

## hopper (`hopper.py`)

    ./hopper.py [--config FILE] watch [--once]
    ./hopper.py [--config FILE] release <launcher|translations> <commit>
    ./hopper.py [--config FILE] release patrons
    ./hopper.py [--config FILE] status

hopper moves releases through their stages. For now it is the trigger, for two streams:
`launcher` (`LAUNCHER_BRANCH` of `LAUNCHER_REPO`, built by `release-build.py`) and
`translations` (`TRANSLATIONS_BRANCH` of `TRANSLATIONS_REPO`, built by
`translations-build.py`). `watch` looks at the head of each every `WATCH_INTERVAL` seconds
(`git ls-remote`), and a commit it hasn't handled goes through the stream's build,
`deploy.py` and `publish.py`, each only if the one before succeeded. It also runs
scheduled jobs, with cron-style schedules (`cron.py`): `patrons` (`patrons-update.py` on
`PATRONS_SCHEDULE`, only where `PATRONS_CONFIG` is set). A scheduled job runs once for the
most recent scheduled time it hasn't handled: after the machine was off, once, not once
per missed time. A release whose deploy changed nothing (e.g. a
Translations commit that only updates the template) is published as a no-op. It builds and publishes nothing itself, so every
step can still be run and inspected by hand. Tagging, promotion, purging and the backend
for a UI are meant to join it as further commands, working on the same files tree and
plain state files (see `UPDATER.md` next to the Toolchains repo).

- **State:** `HOPPER_STATE` (JSON, one list per stream) records every handled commit: time, build number,
  release directory, status (`published`, `failed`, `interrupted`, `adopted`) and the step
  it stopped at; `status` prints it. Each run's output goes to `HOPPER_STATE.logs/`.
- **Fails closed:** a failed step stops the chain; a failed or interrupted commit is not
  retried automatically (`release <stream> <commit>` retries it by hand). The next commit is handled
  normally.
- **First start:** for a stream with no records, the current head is recorded as
  `adopted`, not built: it is assumed to be released already (at cutover, TeamCity's last
  release).
- **Release builds started by hand** (or by anything else) make hopper skip that look and
  try again next time, rather than record a clash as a failure.
- **Housekeeping:** after a successful publish, `releases.py cleanup` (in the same log); its
  failure is logged and doesn't change the release's status.
- **Stopping:** SIGTERM or Ctrl-C stops the running step and records the commit as
  `interrupted`; an entry still `running` when hopper starts (after a crash or kill) is
  recorded as `interrupted` too. One hopper per state file.

### On mikoshi (`systemd/hopper@.service`)

hopper runs on mikoshi, which stays on, as the `hopper` user (home `/srv/hopper`, the
checkout in `~/Toolchains`, its secrets in `~/.config/multimc-deploy/`, rootless podman,
not in the docker group). Its only access to deth001 is the key tied to `hopper-ssh`.
systemd only keeps `hopper.py watch` running, as a user unit with one instance per
settings file: `hopper@files2` (`files2.env`), at cutover `hopper@production`
(`production.env`). The unit sets `CONTAINER_ENGINE=podman` and a low CPU and IO priority
(the containers inherit it), stops hopper with SIGTERM alone so it can stop its own step,
and restarts it if it crashes. Nothing else lives outside the code.

    systemctl --user link ~/Toolchains/automation/systemd/hopper@.service
    systemctl --user enable --now hopper@files2
    journalctl _SYSTEMD_USER_UNIT=hopper@files2.service -f    # as an admin
    ./hopper.py --config files2.env status

hopper's output goes to the system journal, readable by an admin but not by hopper (a
system user's uid gets no journal of its own); each run's output is also in
`HOPPER_STATE.logs/`.

The unit is linked from the checkout, so after a `git pull` that changes it:
`systemctl --user daemon-reload` and a restart. A `git pull` that changes the scripts takes
effect at hopper's next step (each step is a new process); `hopper.py` itself, after a
restart.

Verified 2026-10-24 on files2: first start adopted the head; a new commit went through all
steps (build 5006, published with the cache purge, 2.5 min); a commit that doesn't exist was
recorded as failed with nothing deployed; a look while a release build ran was skipped
without a record; a second hopper was refused; SIGTERM mid-build stopped everything within
a second and recorded the commit as interrupted.

Verified 2026-10-25 on files2, translations stream: the first look adopted the head; a test
commit changing one German string (in a local scratch repo) was released in 8 s, its publish
list just `de.qm` and `index_v2.json`; then the real `master` (1e543c81, the new
`release.py`) in 9 s, after which files2's `de.qm` was byte-identical to production's, built
by TeamCity's old pipeline.

## Requirements

Docker with the toolchain images built or loaded (`../containers/`), git, python3 (3.12+),
rsync, outbound access to GitHub.
