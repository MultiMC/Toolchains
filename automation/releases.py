#!/usr/bin/env python3
"""The releases in RELEASES_DIR: list them, clean up old ones.

    releases.py [--config FILE] list
    releases.py [--config FILE] cleanup [--dry-run]

list     every release, oldest first within each kind (launcher, translations, patrons,
         template), with its size and whether it was trimmed
cleanup  Launcher releases older than the newest RELEASES_KEEP_BUILD_TREES lose build/ and
         src/ (the compiler trees and the checkout; a TRIMMED file says when): what's left,
         packages/, deploy/, logs, compat reports and manifest.json, is enough to deploy it
         again. Of each kind, only the newest RELEASES_KEEP are kept at all. Nothing younger
         than RELEASES_MIN_AGE_HOURS is touched; leftovers of interrupted builds
         (.preparing-*) are removed once they are older. hopper runs it after each publish.
         Skipped while a release build is running.
"""

import argparse
import subprocess
import time

import common

log = common.logger("releases")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("cleanup").add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = common.load_settings(args.config)
    if args.command == "list":
        list_releases(settings)
        return

    if common.is_locked(common.RELEASE_LOCK):
        log("a release build is running; not cleaning up now")
        return
    with common.lock_release():
        done = common.cleanup_releases(settings, dry_run=args.dry_run)
    for action, name in done:
        log("%s %s" % ("would be " + action if args.dry_run else action, name))
    log("%d releases %s" % (len(done), "would change" if args.dry_run else "changed"))


def list_releases(settings):
    for release in common.releases(settings):
        size = subprocess.run(["du", "-sh", str(release)], stdout=subprocess.PIPE, text=True).stdout.split()[0]
        print("%-48s %-13s %-17s %6s%s" % (release.name, common.release_kind(release) or "leftover",
                                           time.strftime("%Y-%m-%d %H:%M", time.localtime(common.release_time(release))),
                                           size, "   trimmed" if (release / common.TRIMMED).exists() else ""))


if __name__ == "__main__":
    main()
