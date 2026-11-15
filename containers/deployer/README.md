# deployer: deploy tools

Image `multimc/toolchains/deployer:dev`: `rclone`, from primary sources only. hopper's
`files/publish.py` and `website/publish.py` use it for the R2 buckets.

    docker build -t multimc/toolchains/deployer:dev .

| Piece | From |
|-------|------|
| base | `debian:bookworm-slim` (12.15), pinned by digest, the same base as `translations` and `macos-osx64` |
| `python3` 3.11.2 (unpacks rclone's zip), `ca-certificates` | Debian 12 packages |
| `rclone` 1.75.2 | downloads.rclone.org, checksum pinned in the Dockerfile (from rclone's `SHA256SUMS`, PGP signature checked 2026-10-24) |

Why not Debian's rclone: Debian 12's 1.60.1 gets `501 NotImplemented` from R2 on every
upload. The object is written anyway, and the retry then finds nothing to do, so a job
still succeeds, but every upload logs errors (first seen in launcher-files2:2, 2026-10-30,
after which the build server went back to the old image).

## History

Until 2026-10-30 this image was TeamCity's `deployer` image from the deth001 snapshot
(`../../snapshots/2026-10-21-deth001/images/toolchains-deployer.tar.zst`: Ubuntu 22.04,
repoman2 c93931e with boto 2.49.0 from pip, s3cmd 2.2.0, `patronupdater.py` with
`patreon` 0.3.1), with upstream rclone 1.75.2 added on top. Nothing used s3cmd (replaced by
rclone on 2026-10-24) or patronupdater (replaced by hopper's `patrons/update.py`, since
Patreon's API v1 is gone).

From 2026-10-30 to the new updater's cutover (2026-11-15) it also had `repoman`:
github.com/MultiMC/repoman2 at `4ce9a73b9a84b16fc35053415ad23eeb1bd7b10e` (c93931e without
the S3 backend; the `repoman/` package only, plus a three-line `/usr/local/bin/repoman`
doing what pip's entry point did), with which hopper's `files/deploy.py` put Launcher
builds into the old update layout. After the cutover nothing deploys there any more;
repoman was removed and repoman2 archived.

## Verification (2026-10-30, against the snapshot-based image)

- **repoman** (removed since): the image's sources are those of 4ce9a73 (sha256 of all 10 `.py` files;
  c93931e's 11 minus `backend/s3.py`). The same deploy as `files/deploy.py` (lin64
  `mmc-develop-lin64.tar.gz` from the snapshot as build 9999 into the develop channel;
  `update/config.json`, `lin64/channels.json` and `develop/index.json` from
  files.multimc.org; one store file already present) gives identical output and
  byte-identical trees (old image vs this one) with identical modes: 7 store files added,
  1 reused, `9999.json` written, index 1479 → 1480 versions. Run for real by
  launcher-files2:2 (build 5021, files2), with Debian's rclone at the time.
- **rclone:** the binary is the old image's (same sha256). A real upload with hopper's
  flags (`copy --files-from-raw` of one test object into `r2:multimc-files2/_rclone-test/`,
  then `delete`) works with it, and fails with Debian's 1.60.1 as above.

Not covered: `website/publish.py`'s `sync` (the same rclone binary as before).
