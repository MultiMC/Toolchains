#!/usr/bin/env python3
"""Publish a release that deploy.py put into the local files tree (FILES_ROOT).

    publish.py [--config FILE] [--dry-run] [--no-bucket] [--no-purge] <release dir>

Works only from the release's publish.json, which deploy.py wrote: every file the deploy
added, changed or removed in the tree, with its SHA-256 before and after. Any kind of
release (Launcher builds, translations) is published the same way.

1. Checks the local tree: every listed file must still be as the deploy left it (another
   deploy since then would make this release's list wrong).
2. With FILES_ORIGIN set (a live tree other jobs also write to, like deth001's): checks
   that every listed file on the live tree is either its "before" or its "after" version,
   so nothing changed there that this release doesn't know about (and publishing again,
   or after an interruption, still works). Then copies the files there, as
   FILES_ORIGIN_OWNER with mode FILES_ORIGIN_MODE, each replaced atomically, in an order
   that never lets clients see an index whose files aren't there yet: store files,
   translation files, version files, indexes, downloads, anything else; removals last.
3. The bucket (BUCKET_TARGET, an rclone remote:path; the rclone config with its key is
   BUCKET_CONFIG, outside this repo) gets the same changes, plus the download symlinks
   pointing at changed packages (the bucket has copies of them). With FILES_ORIGIN empty,
   the whole tree is synced to the bucket instead.
4. Purges every changed or removed file (and those symlinks) from Cloudflare's cache at
   PUBLIC_URL. Needs CLOUDFLARE_ZONE_ID and an API token with Zone / Cache Purge
   permission in the file CLOUDFLARE_TOKEN (outside this repo). If it fails, publishing
   again retries it.

rclone transfers and compares many files at once (32); it compares by size and MD5, so
objects uploaded earlier aren't uploaded again.

--dry-run only reads: shows what would be copied, removed, uploaded and purged.
--no-bucket skips the bucket, --no-purge the purge (otherwise both are required).
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
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

    release = args.release.resolve()
    common.read_release(release)
    changes = common.read_publish_list(release)
    origin = settings["FILES_ORIGIN"]
    root = Path(settings["FILES_ROOT"])
    log("%s%s: %d files -> %s" % ("(dry run) " if args.dry_run else "", release.name, len(changes),
                                  origin or settings["BUCKET_TARGET"]))

    if not changes:
        log("nothing to publish: the deploy changed nothing in the tree")
        return

    with common.lock_files(settings):
        check_local(root, changes)
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


def check_local(root, changes):
    """Every listed file must still be as the deploy left it."""
    for path, change in sorted(changes.items()):
        full = root / path
        now = common.sha256_file(full) if full.is_file() else None
        if now != change["new"]:
            common.die("%s changed in the local tree since this release was deployed (another deploy?); "
                       "publish that one instead, or restore and deploy again" % path)


def live_hashes(settings, paths):
    """{path: sha256 or None} for these paths in the live tree (FILES_ORIGIN: host:dir or a dir)."""
    origin = settings["FILES_ORIGIN"]
    if not paths:
        return {}
    if ":" not in origin:
        return {path: common.sha256_file(Path(origin) / path) if (Path(origin) / path).is_file() else None
                for path in paths}

    host, directory = origin.split(":", 1)
    script = ('cd %s && while IFS= read -r f; do if [ -f "$f" ]; then sha256sum -- "$f"; '
              'else printf -- "- %%s\\n" "$f"; fi; done' % shlex.quote(directory))
    result = common.run("ssh", host, script, input="\n".join(paths) + "\n", stdout=subprocess.PIPE, text=True)
    hashes = {}
    for line in result.stdout.splitlines():
        digest, path = line.split(None, 1)
        hashes[path.strip()] = None if digest == "-" else digest
    return hashes


def check_live(settings, changes):
    """Every listed file on the live tree must be its before or its after version."""
    live = live_hashes(settings, sorted(changes))
    unexpected = [path for path, change in sorted(changes.items())
                  if live.get(path, "missing from the answer") not in (change["old"], change["new"])]
    if unexpected:
        common.die("the live tree changed in ways this release doesn't know about (another deploy?): %s; "
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
        common.run("ssh", host, "cd %s && xargs -d '\\n' rm -f --" % shlex.quote(directory),
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
