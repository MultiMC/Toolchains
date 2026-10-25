#!/usr/bin/env python3
"""Publish the local files tree (FILES_ROOT): everything that changed since the last publish.

    publish.py [--config FILE] [--dry-run] [--no-bucket] [--no-purge]

What was last published is a snapshot of the tree, named in FILES_ROOT.published. The
difference between it and the tree now is what gets published, whatever deploys made it
(Launcher builds, translations, Patreon credits; one or several); a successful publish then
records a new snapshot. Restoring an earlier snapshot and publishing puts the live site
back to it.

1. With FILES_ORIGIN set (a live tree other jobs also write to, like deth001's): checks
   that every changed file on the live tree is either its published or its new version,
   so nothing changed there that this publish doesn't know about (and publishing again,
   or after an interruption, still works). Then copies the files there, as
   FILES_ORIGIN_OWNER with mode FILES_ORIGIN_MODE, each replaced atomically, in an order
   that never lets clients see an index whose files aren't there yet: store files,
   translation files, version files, indexes, downloads, anything else; removals last.
2. The bucket (BUCKET_TARGET, an rclone remote:path; the rclone config with its key is
   BUCKET_CONFIG, outside this repo) gets the same changes, plus the download symlinks
   pointing at changed packages (the bucket has copies of them). With FILES_ORIGIN empty,
   the whole tree is synced to the bucket instead.
3. Purges every changed or removed file (and those symlinks) from Cloudflare's cache at
   PUBLIC_URL. Needs CLOUDFLARE_ZONE_ID and an API token with Zone / Cache Purge
   permission in the file CLOUDFLARE_TOKEN (outside this repo). If it fails, publishing
   again retries it (nothing is recorded as published until everything succeeded).

rclone transfers and compares many files at once (32); it compares by size and MD5, so
objects uploaded earlier aren't uploaded again.

--dry-run only reads: shows what would be copied, removed, uploaded and purged.
--no-bucket skips the bucket, --no-purge the purge (otherwise both are required).
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

import common

log = common.logger("publish")

TRANSLATION_INDEXES = ("translations/index_v2.json", "translations/index")

# Publishing order: whatever an index points at goes before the index.
STAGES = [
    ("store files", lambda path: path.startswith("files/")),
    ("translation files", lambda path: path.startswith("translations/") and path not in TRANSLATION_INDEXES),
    ("version files", lambda path: re.fullmatch(r"update/[^/]+/[^/]+/\d+\.json", path)),
    ("indexes", lambda path: path.startswith("update/") or path in TRANSLATION_INDEXES),
    ("downloads", lambda path: path.startswith("downloads/")),
    ("other files", lambda path: True),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-bucket", action="store_true")
    parser.add_argument("--no-purge", action="store_true")
    args = parser.parse_args()

    settings = common.load_settings(args.config)
    bucket = not args.no_bucket
    if bucket and not (settings["BUCKET_TARGET"] and Path(settings["BUCKET_CONFIG"]).is_file()):
        common.die("no bucket: BUCKET_TARGET and the rclone config BUCKET_CONFIG (%s) are needed "
                   "(or use --no-bucket)" % settings["BUCKET_CONFIG"])

    purge = not args.no_purge
    if purge and not (settings["PUBLIC_URL"] and settings["CLOUDFLARE_ZONE_ID"]
                      and Path(settings["CLOUDFLARE_TOKEN"]).is_file()):
        common.die("can't purge Cloudflare's cache: PUBLIC_URL, CLOUDFLARE_ZONE_ID and the token "
                   "file CLOUDFLARE_TOKEN (%s) are needed (or use --no-purge)" % settings["CLOUDFLARE_TOKEN"])

    origin = settings["FILES_ORIGIN"]
    root = Path(settings["FILES_ROOT"])
    with common.lock_files(settings):
        published = common.published_snapshot(settings)
        changes = common.tree_changes(published, root)
        log("%s%d files changed since %s -> %s" % ("(dry run) " if args.dry_run else "", len(changes),
                                                   published.name, origin or settings["BUCKET_TARGET"]))
        if not changes:
            log("nothing to publish")
            return

        stages = in_stages(changes)
        removed = sorted(path for path, change in changes.items() if change["new"] is None)
        links = links_to(root / "downloads", [p for _, paths in stages for p in paths])

        if origin:
            check_live(settings, changes)
            for what, paths in stages:
                copy(settings, what, paths, args.dry_run)
            remove_live(settings, removed, args.dry_run)

        if bucket and origin:
            for what, paths in stages:
                upload_to_bucket(settings, what, paths + (links if what == "downloads" else []), args.dry_run)
            remove_from_bucket(settings, removed, args.dry_run)
        elif bucket:
            sync_bucket(settings, args.dry_run)

        if purge:
            purge_cache(settings, sorted(changes) + links, args.dry_run)

        if not args.dry_run:
            published = common.mark_published(settings, "published", about="%d files published" % len(changes))
            log("recorded as published: %s" % published.name)
            removed = common.cleanup_snapshots(settings)
            if removed:
                log("removed %d old snapshots" % len(removed))
    skipped = [name for name, done in (("bucket", bucket), ("purge", purge)) if not done]
    log("done" + (", skipped: " + " ".join(skipped) if skipped else ""))


def in_stages(changes):
    """The added and changed files, as [(stage, paths)] in publishing order."""
    stages = [(name, []) for name, _ in STAGES]
    for path, change in sorted(changes.items()):
        if change["new"] is not None:
            index = next(i for i, (_, matches) in enumerate(STAGES) if matches(path))
            stages[index][1].append(path)
    return [(name, paths) for name, paths in stages if paths]


def links_to(directory, paths):
    """Symlinks in `directory` that point at one of `paths` (relative to the tree). The bucket and
    Cloudflare have copies of what they point at; the live tree has the links themselves."""
    names = {os.path.basename(p) for p in paths if p.startswith(directory.name + "/")}
    return sorted("%s/%s" % (directory.name, link.name) for link in directory.iterdir()
                  if link.is_symlink() and os.path.basename(os.readlink(link)) in names)


def live_hashes(settings, paths):
    """{path: sha256 or None} for these paths in the live tree (FILES_ORIGIN: host:dir or a dir).
    On a host, through hopper-ssh (remote/hopper-ssh, installed there), the only commands the
    automation's key may run besides rsync."""
    origin = settings["FILES_ORIGIN"]
    if not paths:
        return {}
    if ":" not in origin:
        return {path: common.sha256_file(Path(origin) / path) if (Path(origin) / path).is_file() else None
                for path in paths}

    host, directory = origin.split(":", 1)
    result = common.run("ssh", host, "hopper-ssh", "hash", directory.rstrip("/"),
                        input="\n".join(paths) + "\n", stdout=subprocess.PIPE, text=True)
    hashes = {}
    for line in result.stdout.splitlines():
        digest, path = line.split("  ", 1)
        hashes[path] = None if digest == "-" else digest
    return hashes


def check_live(settings, changes):
    """Every changed file on the live tree must be its published or its new version."""
    live = live_hashes(settings, sorted(changes))
    unexpected = [path for path, change in sorted(changes.items())
                  if live.get(path, "missing from the answer") not in (change["old"], change["new"])]
    if unexpected:
        common.die("the live tree changed in ways this publish doesn't know about (another deploy?): %s; "
                   "run files-pull.py and deploy again" % ", ".join(unexpected[:5]))
    done = sum(1 for path, change in changes.items() if live[path] == change["new"])
    if done:
        log("  %d of %d files are already published" % (done, len(changes)))


def remove_live(settings, paths, dry_run):
    if not paths:
        return
    log("live tree: removing %d files" % len(paths))
    if dry_run:
        for path in paths:
            print("    remove " + path)
        return
    origin = settings["FILES_ORIGIN"]
    if ":" in origin:
        host, directory = origin.split(":", 1)
        common.run("ssh", host, "hopper-ssh", "remove", directory.rstrip("/"),
                   input="\n".join(paths) + "\n", text=True)
    else:
        for path in paths:
            (Path(origin) / path).unlink(missing_ok=True)


def copy(settings, what, paths, dry_run, *options):
    """rsync the given paths (relative to FILES_ROOT) to the live tree, as FILES_ORIGIN_OWNER
    with mode FILES_ORIGIN_MODE; each file is replaced atomically."""
    log("live tree: %s (%d)" % (what, len(paths)))
    result = common.run("rsync", "-tp", "--omit-dir-times", "--files-from=-", "--itemize-changes",
                        "--chown=" + settings["FILES_ORIGIN_OWNER"], "--chmod=F" + settings["FILES_ORIGIN_MODE"],
                        *(["--dry-run"] if dry_run else []), *options,
                        settings["FILES_ROOT"] + "/", settings["FILES_ORIGIN"],
                        input="\n".join(paths) + "\n", stdout=subprocess.PIPE, text=True)
    for line in result.stdout.splitlines():
        print("    " + line)


def rclone(settings, *args, **kwargs):
    """rclone with FILES_ROOT at /deploy/files (read-only)."""
    common.rclone(settings, *args, mount=(settings["FILES_ROOT"], "/deploy/files"), **kwargs)


def upload_to_bucket(settings, what, paths, dry_run):
    """Upload the given paths (relative to FILES_ROOT) to BUCKET_TARGET, unless already there."""
    log("bucket: %s (%d)" % (what, len(paths)))
    rclone(settings, "copy", "--files-from-raw", "-", *(["--dry-run"] if dry_run else []),
           "/deploy/files", settings["BUCKET_TARGET"], input="\n".join(paths) + "\n", text=True)


def remove_from_bucket(settings, paths, dry_run):
    if not paths:
        return
    log("bucket: removing %d files" % len(paths))
    rclone(settings, "delete", "--files-from-raw", "-", *(["--dry-run"] if dry_run else []),
           settings["BUCKET_TARGET"], input="\n".join(paths) + "\n", text=True)


def sync_bucket(settings, dry_run):
    """Make BUCKET_TARGET an exact copy of FILES_ROOT."""
    log("bucket: sync %s -> %s" % (settings["FILES_ROOT"], settings["BUCKET_TARGET"]))
    rclone(settings, "sync", *(["--dry-run"] if dry_run else []), "/deploy/files", settings["BUCKET_TARGET"])


def purge_cache(settings, paths, dry_run):
    """Evict these paths (relative to FILES_ROOT) from Cloudflare's cache at PUBLIC_URL."""
    log("Cloudflare: purging %d URLs under %s" % (len(paths), settings["PUBLIC_URL"]))
    common.purge_cache(settings, [settings["PUBLIC_URL"].rstrip("/") + "/" + path for path in paths], dry_run,
                       "everything else is published; publish again to retry")


if __name__ == "__main__":
    main()
