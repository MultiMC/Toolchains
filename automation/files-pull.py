#!/usr/bin/env python3
"""Make the local files tree (FILES_ROOT) an exact copy of the live one (FILES_ORIGIN).

    files-pull.py [--config FILE] [--dry-run]

Overwrites local changes (rsync --delete): whatever deploy.py put there is gone afterwards.
"""

import argparse

import common


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = common.load_settings(args.config)
    common.logger("files-pull")("pulling %s -> %s" % (settings["FILES_ORIGIN"], settings["FILES_ROOT"]))
    common.pull_files(settings, args.dry_run)


if __name__ == "__main__":
    main()
