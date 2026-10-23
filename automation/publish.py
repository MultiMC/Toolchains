#!/usr/bin/env python3
"""Publish a release that deploy.py put into the local files tree (FILES_ROOT).

    publish.py [--config FILE] [--dry-run] [--no-s3] <release dir>

What a release adds to the tree, in the order it is published, so clients never see a
version whose files aren't there yet: the version's store files (files/), the version
files, the channel indexes, the download packages.

With FILES_ORIGIN set (a live tree other jobs also write to, like deth001's):
1. Checks that each channel's index.json on the live tree is the local one without this
   release (or already includes it), so a version deployed elsewhere meanwhile isn't lost.
2. Copies those files to the live tree (store files only if missing). Each file is
   replaced atomically.
3. Uploads the same files to S3_TARGET, plus the download symlinks pointing at the
   packages (S3 has copies of them). Only this release's files: the translations and
   Patreon jobs upload what they change themselves.

With FILES_ORIGIN empty, FILES_ROOT is the only copy and the bucket is served directly
(files2: R2 behind files2.multimc.org): the whole tree is synced to the bucket, deleting
what the tree no longer has.

--dry-run only reads: shows what would be copied and uploaded.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

import common

log = common.logger("publish")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-s3", action="store_true")
    parser.add_argument("release", type=Path)
    args = parser.parse_args()

    settings = common.load_settings(args.config)
    s3 = not args.no_s3
    if s3 and not Path(settings["S3_CONFIG"]).is_file():
        common.die("no S3 key at %s (or use --no-s3)" % settings["S3_CONFIG"])

    manifest = common.read_release(args.release.resolve())
    branch, build = manifest["branch"], str(manifest["build_number"])
    platforms = [common.platform(name) for name in manifest["platforms"]]
    origin = settings["FILES_ORIGIN"]
    root = Path(settings["FILES_ROOT"])
    log("%srelease %s build %s: %s -> %s" % ("(dry run) " if args.dry_run else "", branch, build,
                                           " ".join(p.name for p in platforms), origin or settings["S3_TARGET"]))

    with common.lock_files(settings):
        for p in platforms:
            if not (root / "update" / p.name / branch / (build + ".json")).is_file():
                common.die("update/%s/%s/%s.json isn't in %s (run deploy.py)" % (p.name, branch, build, root))

        if not origin:
            if s3:
                sync_s3(settings, args.dry_run)
            log("done")
            return

        check_live_indexes(settings, platforms, branch, build)
        groups = release_files(root, platforms, branch, build)
        for what, paths in groups:
            copy(settings, what, paths, args.dry_run, *(["--ignore-existing"] if what == "store files" else []))
        if s3:
            for what, paths in groups:
                if what == "downloads":
                    paths = paths + links_to(root / "downloads", paths)
                upload_s3(settings, what, paths, args.dry_run)
    log("done" if s3 else "done, S3 skipped")


def release_files(root, platforms, branch, build):
    """The files the release added, relative to FILES_ROOT, as (what, paths) in publishing order."""
    store, versions, indexes, downloads = set(), [], [], []
    for p in platforms:
        channel = "update/%s/%s" % (p.name, branch)
        version = json.loads((root / channel / (build + ".json")).read_text())
        store |= {"files/" + os.path.basename(s["Url"]) for f in version["Files"] for s in f["Sources"]}
        versions.append("%s/%s.json" % (channel, build))
        indexes.append(channel + "/index.json")
        downloads.append("downloads/" + p.package(branch))
    return [("store files", sorted(store)), ("version files", versions),
            ("channel indexes", indexes), ("downloads", downloads)]


def links_to(directory, paths):
    """Symlinks in `directory` that point at one of `paths` (relative to the tree)."""
    names = {os.path.basename(p) for p in paths}
    return sorted("%s/%s" % (directory.name, link.name) for link in directory.iterdir()
                  if link.is_symlink() and os.path.basename(os.readlink(link)) in names)


def read_origin(settings, path):
    """A file from the live tree; FILES_ORIGIN is host:dir or a local directory."""
    origin = settings["FILES_ORIGIN"]
    if ":" in origin:
        host, directory = origin.split(":", 1)
        return common.output("ssh", host, "cat '%s/%s'" % (directory.rstrip("/"), path))

    return (Path(origin) / path).read_text()


def check_live_indexes(settings, platforms, branch, build):
    """Each live index must be the local one minus this build, or already include it."""
    root = Path(settings["FILES_ROOT"])
    for p in platforms:
        channel = "update/%s/%s" % (p.name, branch)
        local = common.channel_versions((root / channel / "index.json").read_text())
        live = common.channel_versions(read_origin(settings, channel + "/index.json"))
        if local == live and local[-1]["Id"] == build:
            log("  %s: build %s is already in the live index" % (p.name, build))
        elif not (local[:-1] == live and local[-1]["Id"] == build):
            common.die("%s: the live index.json isn't the local one minus build %s (deployed elsewhere "
                       "meanwhile?); run files-pull.py and deploy.py again" % (p.name, build))


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


def s3cmd(settings, *args, **kwargs):
    """Run s3cmd in the deployer image, with FILES_ROOT at /deploy/files (read-only).
    --no-preserve: no owner/mode/time metadata on the objects (nothing reads it, and the
    container doesn't know the calling user, so s3cmd warned for every file). s3cmd still
    stores the MD5 it compares large (multipart) files by."""
    common.run("docker", "run", "--rm", "-i", "-u", common.user(), "-e", "HOME=/tmp",
               "-v", "%s:/deploy/files:ro" % settings["FILES_ROOT"],
               "-v", "%s:/private/s3cmd.cfg:ro" % settings["S3_CONFIG"],
               settings["IMAGE_DEPLOYER"], "s3cmd", "-c", "/private/s3cmd.cfg", *args,
               "--follow-symlinks", "--no-preserve", **kwargs)


def upload_s3(settings, what, paths, dry_run):
    """Upload the given paths (relative to FILES_ROOT) to S3_TARGET, unless already there."""
    log("S3: %s (%d)" % (what, len(paths)))
    s3cmd(settings, "sync", "--files-from=-", *(["--dry-run"] if dry_run else []),
          "/deploy/files/", settings["S3_TARGET"], input="\n".join(paths) + "\n", text=True)


def sync_s3(settings, dry_run):
    """Make S3_TARGET an exact copy of FILES_ROOT."""
    log("S3: sync %s/ -> %s" % (settings["FILES_ROOT"], settings["S3_TARGET"]))
    s3cmd(settings, "sync", "-v", "--delete-removed", *(["--dry-run"] if dry_run else []),
          "/deploy/files/", settings["S3_TARGET"])


if __name__ == "__main__":
    main()
