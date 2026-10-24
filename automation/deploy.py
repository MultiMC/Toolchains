#!/usr/bin/env python3
"""Deploy a release made by release-build.py into the local files tree (FILES_ROOT).

    deploy.py [--config FILE] <release dir>

Does what TeamCity's deploy steps did on deth001, with the same repoman (IMAGE_DEPLOYER),
as the calling user, without network: for each platform,

    repoman -c update push <platform> <branch> <build> <version> <bundle>/
    repoman push-file downloads <package>

which adds update/<platform>/<branch>/<build>.json, adds it to the channel's index.json,
copies files the store doesn't have yet into files/<md5>-<name>, and replaces the download
package. Nothing is published; the tree stays local (publish.py does that).
Before changing the tree it takes a read-only snapshot of it (files-snapshots.py lists and
restores them); a tree that isn't a btrfs subvolume is refused.

Refuses a release that isn't releasable, one built for another tree (its UPDATER_BASE must
be the tree's update/config.json base_url), and one whose build number isn't higher than
every version already in the channel (the updater only offers newer IDs).
"""

import argparse
import json
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
    branch, build, version = manifest["branch"], manifest["build_number"], manifest["version_name"]
    platforms = [common.platform(name) for name in manifest["platforms"]]
    log("release %s build %d (%s): %s" % (branch, build, version, " ".join(p.name for p in platforms)))

    root = Path(settings["FILES_ROOT"])
    if not (root / "update" / "config.json").is_file():
        common.die("no files tree at %s (run files-pull.py)" % root)

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

    log("deployed to %s (not published)" % root)


if __name__ == "__main__":
    main()
