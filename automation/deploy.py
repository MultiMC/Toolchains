#!/usr/bin/env python3
"""Deploy a release into the local files tree (FILES_ROOT): a Launcher build made by
release-build.py, translations made by translations-build.py, or the Patreon credits
made by patrons-update.py.

    deploy.py [--config FILE] <release dir>

Before changing the tree it takes a read-only snapshot of it (files-snapshots.py lists and
restores them; a tree that isn't a btrfs subvolume is refused). Afterwards it compares the
tree with that snapshot and writes what changed to <release>/publish.json, which is what
publish.py publishes. Nothing is published here; the tree stays local. Refuses a release
that isn't releasable.

Launcher builds: does what TeamCity's deploy steps did on deth001, with the same repoman
(IMAGE_DEPLOYER), as the calling user, without network: for each platform,

    repoman -c update push <platform> <branch> <build> <version> <bundle>/
    repoman push-file downloads <package>

which adds update/<platform>/<branch>/<build>.json, adds it to the channel's index.json,
copies files the store doesn't have yet into files/<md5>-<name>, and replaces the download
package. Refuses a build made for another tree (its UPDATER_BASE must be the tree's
update/config.json base_url), and one whose build number isn't higher than every version
already in the channel (the updater only offers newer IDs).

Translations: translations/ becomes the release's files, plus the files of languages that
kept their previous release (still named in the new index); everything else in there is
removed, so nothing piles up.

Patreon credits: patrons.txt replaces the tree's.
"""

import argparse
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

import common

log = common.logger("deploy")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("release", type=Path)
    args = parser.parse_args()

    settings = common.load_settings(args.config)
    release = args.release.resolve()
    manifest = common.read_release(release)
    root = Path(settings["FILES_ROOT"])
    if not (root / "update" / "config.json").is_file():
        common.die("no files tree at %s (run files-pull.py)" % root)
    if manifest.get("kind") == "translations":
        deploy_translations(settings, release, manifest, root)
    elif manifest.get("kind") == "patrons":
        deploy_patrons(settings, release, root)
    else:
        deploy_launcher(settings, release, manifest, root)


def deploy_launcher(settings, release, manifest, root):
    branch, build, version = manifest["branch"], manifest["build_number"], manifest["version_name"]
    platforms = [common.platform(name) for name in manifest["platforms"]]
    log("release %s build %d (%s): %s" % (branch, build, version, " ".join(p.name for p in platforms)))

    tree_base = json.loads((root / "update" / "config.json").read_text())["base_url"]
    if manifest.get("updater_base") != tree_base:
        common.die("the release updates from %s, this tree is %s (wrong --config?)"
                   % (manifest.get("updater_base"), tree_base))

    with common.lock_files(settings):
        for p in platforms:
            index = root / "update" / p.name / branch / "index.json"
            versions = common.channel_versions(index.read_text()) if index.exists() else []
            last = max([int(v["Id"]) for v in versions] or [0])
            if build <= last:
                common.die("%s/%s already has build %d; %d is not newer" % (p.name, branch, last, build))

        common.check_no_pending(settings)
        snapshot = common.snapshot_files(settings, "before-deploy-%d" % build)
        log("snapshot of the tree as it was: %s" % snapshot.name)

        with tempfile.TemporaryDirectory(dir=release, prefix=".deploy.") as work:
            for p in platforms:
                bundle_dir = Path(work) / p.name
                with tarfile.open(release / "deploy" / ("%s.tar.gz" % p.name)) as tar:
                    tar.extractall(bundle_dir, filter="data")
                package = p.package(branch)
                log("%s: pushing version %d to %s, then %s to downloads/" % (p.name, build, branch, package))
                repoman = ["docker", "run", "--rm", "--init", "--network", "none", "-u", common.user(), "-e", "HOME=/tmp",
                           "-v", "%s:/deploy/files" % root, "-v", "%s:/bundle:ro" % bundle_dir,
                           "-v", "%s:/packages:ro" % (release / "packages"),
                           "-w", "/deploy/files", settings["IMAGE_DEPLOYER"], "repoman"]
                common.run(*repoman, "-c", "update", "push", p.name, branch, build, version, "/bundle/%s/" % p.bundle)
                common.run(*repoman, "push-file", "downloads", "/packages/" + package)

        changes = common.tree_changes(snapshot, root)
        common.write_publish_list(settings, release, snapshot, changes)

    log("deployed to %s (not published); %d files to publish, see %s"
        % (root, len(changes), release / "publish.json"))



def deploy_translations(settings, release, manifest, root):
    build = release / "build"
    with open(build / "index_v2.json") as f:
        index = json.load(f)
    keep = set(manifest["files"]) | {entry["file"] for entry in index["languages"].values()}
    with open(build / "index") as f:
        keep |= {line.strip() for line in f if line.strip()}
    log("translations from %s: %d files" % (manifest["commit"][:10], len(manifest["files"])))

    target = root / "translations"
    with common.lock_files(settings):
        missing = sorted(name for name in keep - set(manifest["files"]) if not (target / name).is_file())
        if missing:
            common.die("the new index names files that are neither in the release nor in the tree: %s"
                       % ", ".join(missing))
        common.check_no_pending(settings)
        snapshot = common.snapshot_files(settings, "before-translations-%s" % manifest["commit"][:10])
        log("snapshot of the tree as it was: %s" % snapshot.name)

        target.mkdir(exist_ok=True)
        for name in manifest["files"]:
            shutil.copyfile(build / name, target / name)
        removed = sorted(name for name in os.listdir(target) if name not in keep)
        for name in removed:
            (target / name).unlink()
        log("%d files copied, %d removed" % (len(manifest["files"]), len(removed)))

        changes = common.tree_changes(snapshot, root)
        common.write_publish_list(settings, release, snapshot, changes)

    log("deployed to %s (not published); %d files to publish, see %s"
        % (root, len(changes), release / "publish.json"))



def deploy_patrons(settings, release, root):
    with common.lock_files(settings):
        common.check_no_pending(settings)
        snapshot = common.snapshot_files(settings, "before-patrons")
        log("snapshot of the tree as it was: %s" % snapshot.name)
        shutil.copyfile(release / "patrons.txt", root / "patrons.txt")
        changes = common.tree_changes(snapshot, root)
        common.write_publish_list(settings, release, snapshot, changes)

    log("deployed to %s (not published); %d files to publish, see %s"
        % (root, len(changes), release / "publish.json"))


if __name__ == "__main__":
    main()
