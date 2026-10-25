#!/usr/bin/env python3
"""Snapshots of the local files tree (FILES_ROOT): list, take, restore, remove.

    files-snapshots.py [--config FILE] list
    files-snapshots.py [--config FILE] create <label>
    files-snapshots.py [--config FILE] restore <snapshot>
    files-snapshots.py [--config FILE] remove <snapshot>...
    files-snapshots.py [--config FILE] init

FILES_ROOT is a btrfs subvolume; its read-only snapshots are kept next to it, in
FILES_ROOT.snapshots/<time>-<label>. deploy.py and files-pull.py take one before every
change. They can be inspected like any directory (diff, ls), or restored.

list     the snapshots, oldest first
create   take a snapshot now, e.g. before changing the tree by hand
restore  make the tree the same as the snapshot again; takes a snapshot of the current
         state first, so a restore can be undone too
remove   delete snapshots (without root: clears the read-only flag, empties it, rmdir)
init     turn an existing FILES_ROOT directory into a subvolume (copies it with reflinks,
         compares, swaps). The old directory is kept as FILES_ROOT.pre-subvolume for you to
         delete once you're satisfied.

Restoring changes only the local tree; publish.py decides what goes live.
"""

import argparse
import shutil
import subprocess
from pathlib import Path

import common

log = common.logger("snapshots")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("create").add_argument("label")
    commands.add_parser("restore").add_argument("snapshot")
    commands.add_parser("remove").add_argument("snapshot", nargs="+")
    commands.add_parser("init")
    args = parser.parse_args()

    settings = common.load_settings(args.config)
    if args.command == "list":
        list_snapshots(settings)
        return

    with common.lock_files(settings):
        if args.command == "create":
            log("snapshot %s" % common.snapshot_files(settings, args.label).name)
        elif args.command == "restore":
            restore(settings, find(settings, args.snapshot))
        elif args.command == "remove":
            for name in args.snapshot:
                remove(find(settings, name))
        elif args.command == "init":
            init(settings)


def list_snapshots(settings):
    directory = common.snapshots_dir(settings)
    for snapshot in sorted(directory.iterdir()) if directory.is_dir() else []:
        print(snapshot.name)


def find(settings, name):
    snapshot = common.snapshots_dir(settings) / name
    if not common.is_subvolume(snapshot):
        common.die("no snapshot %s (files-snapshots.py list)" % name)
    return snapshot


def restore(settings, snapshot):
    before = common.snapshot_files(settings, "before-restore")
    log("snapshot of the current state: %s" % before.name)
    log("restoring %s" % snapshot.name)
    # --checksum: compare contents, not just size and time (restores are rare, reading is cheap)
    common.run("rsync", "-a", "--delete", "--checksum", "--info=stats1",
               str(snapshot) + "/", settings["FILES_ROOT"] + "/")
    # Deploys made from this snapshot on are undone, so they aren't pending any more.
    common.remove_pending(settings, from_snapshot=snapshot.name)


def remove(snapshot):
    """Without root, btrfs only lets the owner delete a subvolume that is writable and empty."""
    log("removing %s" % snapshot.name)
    common.run("btrfs", "property", "set", snapshot, "ro", "false")
    for entry in snapshot.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    snapshot.rmdir()


def init(settings):
    root = Path(settings["FILES_ROOT"])
    if common.is_subvolume(root):
        common.die("%s is already a subvolume" % root)
    if not root.is_dir():
        common.die("%s doesn't exist (files-pull.py creates it as a subvolume)" % root)
    new, old = Path(str(root) + ".new"), Path(str(root) + ".pre-subvolume")
    if new.exists() or old.exists():
        common.die("%s or %s is in the way" % (new, old))

    log("copying %s into a new subvolume (reflinks: shares the data)" % root)
    common.run("btrfs", "subvolume", "create", new, stdout=subprocess.DEVNULL)
    common.run("cp", "-a", "--reflink=always", str(root) + "/.", str(new) + "/")
    if subprocess.run(["diff", "-r", "--no-dereference", "-q", root, new]).returncode:
        common.die("the copy in %s differs from %s; nothing swapped" % (new, root))

    root.rename(old)
    new.rename(root)
    snapshot = common.snapshot_files(settings, "init")
    log("%s is a subvolume now (first snapshot: %s); the old directory is %s" % (root, snapshot.name, old))


if __name__ == "__main__":
    main()
