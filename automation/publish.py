#!/usr/bin/env python3
"""Publish a release that deploy.py put into the local files tree (FILES_ROOT).

    publish.py [--config FILE] [--dry-run] [--no-bucket] [--no-purge] <release dir>

What a release adds to the tree, in the order it is published, so clients never see a
version whose files aren't there yet: the version's store files (files/), the version
files, the channel indexes, the download packages.

With FILES_ORIGIN set (a live tree other jobs also write to, like deth001's):
1. Checks that each channel's index.json on the live tree is the local one without this
   release (or already includes it), so a version deployed elsewhere meanwhile isn't lost.
2. Copies those files to the live tree (store files only if missing). Each file is
   replaced atomically.
3. Uploads the same files to the bucket (BUCKET_TARGET, an rclone remote:path, with the
   rclone config BUCKET_CONFIG; outside this repo), plus the download symlinks pointing at
   the packages (the bucket has copies of them). Only this release's files: the
   translations and Patreon jobs upload what they change themselves.

With FILES_ORIGIN empty, FILES_ROOT is the only copy: the whole tree is synced to the
bucket, deleting what the tree no longer has.

rclone transfers and compares many files at once (32); it compares by size and MD5, so
objects uploaded earlier (also by s3cmd) aren't uploaded again.

Last, every file of the release (and the download symlinks) is purged from Cloudflare's
cache at PUBLIC_URL, so the overwritten indexes and downloads are served fresh. The list
doesn't depend on what was transferred, so if the purge fails, publishing again retries
it. Needs CLOUDFLARE_ZONE_ID and an API token with Zone / Cache Purge permission in the
file CLOUDFLARE_TOKEN (outside this repo); without them nothing is published, unless
--no-purge.

--dry-run only reads: shows what would be copied, uploaded and purged.
--no-bucket skips the bucket, --no-purge the purge (otherwise both are required).
"""

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import common

log = common.logger("publish")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-bucket", action="store_true")
    parser.add_argument("--no-purge", action="store_true")
    parser.add_argument("release", type=Path)
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

    manifest = common.read_release(args.release.resolve())
    branch, build = manifest["branch"], str(manifest["build_number"])
    platforms = [common.platform(name) for name in manifest["platforms"]]
    origin = settings["FILES_ORIGIN"]
    root = Path(settings["FILES_ROOT"])
    log("%srelease %s build %s: %s -> %s" % ("(dry run) " if args.dry_run else "", branch, build,
                                           " ".join(p.name for p in platforms), origin or settings["BUCKET_TARGET"]))

    with common.lock_files(settings):
        for p in platforms:
            if not (root / "update" / p.name / branch / (build + ".json")).is_file():
                common.die("update/%s/%s/%s.json isn't in %s (run deploy.py)" % (p.name, branch, build, root))

        groups = release_files(root, platforms, branch, build)
        if origin:
            check_live_indexes(settings, platforms, branch, build)
            for what, paths in groups:
                copy(settings, what, paths, args.dry_run, *(["--ignore-existing"] if what == "store files" else []))

        if bucket and origin:
            for what, paths in groups:
                upload_to_bucket(settings, what, paths, args.dry_run)
        elif bucket:
            sync_bucket(settings, args.dry_run)

        if purge:
            purge_cache(settings, [path for _, paths in groups for path in paths], args.dry_run)

    skipped = [name for name, done in (("bucket", bucket), ("purge", purge)) if not done]
    log("done" + (", skipped: " + " ".join(skipped) if skipped else ""))


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
    downloads += links_to(root / "downloads", downloads)
    return [("store files", sorted(store)), ("version files", versions),
            ("channel indexes", indexes), ("downloads", downloads)]


def links_to(directory, paths):
    """Symlinks in `directory` that point at one of `paths` (relative to the tree). The bucket and
    Cloudflare have copies of what they point at; the live tree has the links themselves."""
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


def rclone(settings, *args, **kwargs):
    """Run rclone in the deployer image, with FILES_ROOT at /deploy/files (read-only)."""
    common.run("docker", "run", "--rm", "--init", "-i", "-u", common.user(), "-e", "HOME=/tmp",
               "-v", "%s:/deploy/files:ro" % settings["FILES_ROOT"],
               "-v", "%s:/private/rclone.conf:ro" % settings["BUCKET_CONFIG"],
               settings["IMAGE_DEPLOYER"], "rclone", "--config", "/private/rclone.conf",
               "--checksum", "--copy-links", "--transfers", "32", "--checkers", "32",
               "--stats-one-line", "--stats", "0", "-v", *args, **kwargs)


def upload_to_bucket(settings, what, paths, dry_run):
    """Upload the given paths (relative to FILES_ROOT) to BUCKET_TARGET, unless already there."""
    log("bucket: %s (%d)" % (what, len(paths)))
    rclone(settings, "copy", "--files-from-raw", "-", *(["--dry-run"] if dry_run else []),
           "/deploy/files", settings["BUCKET_TARGET"], input="\n".join(paths) + "\n", text=True)


def sync_bucket(settings, dry_run):
    """Make BUCKET_TARGET an exact copy of FILES_ROOT."""
    log("bucket: sync %s -> %s" % (settings["FILES_ROOT"], settings["BUCKET_TARGET"]))
    rclone(settings, "sync", *(["--dry-run"] if dry_run else []), "/deploy/files", settings["BUCKET_TARGET"])


def purge_cache(settings, paths, dry_run):
    """Evict these paths (relative to FILES_ROOT) from Cloudflare's cache at PUBLIC_URL.
    Purge by URL takes up to 100 URLs per request on the Free plan."""
    urls = [settings["PUBLIC_URL"].rstrip("/") + "/" + path for path in paths]
    log("Cloudflare: purging %d URLs under %s" % (len(urls), settings["PUBLIC_URL"]))
    if dry_run:
        for url in urls:
            print("    " + url)
        return

    token = Path(settings["CLOUDFLARE_TOKEN"]).read_text().strip()
    endpoint = "https://api.cloudflare.com/client/v4/zones/%s/purge_cache" % settings["CLOUDFLARE_ZONE_ID"]
    for start in range(0, len(urls), 100):
        request = urllib.request.Request(endpoint, method="POST",
                                         data=json.dumps({"files": urls[start:start + 100]}).encode(),
                                         headers={"Authorization": "Bearer " + token,
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as e:
            result = {"success": False, "errors": e.read().decode(errors="replace")}
        except urllib.error.URLError as e:
            result = {"success": False, "errors": str(e.reason)}
        if not result.get("success"):
            common.die("the purge failed (everything else is published; publish again to retry): %s"
                       % result.get("errors"))


if __name__ == "__main__":
    main()
