#!/usr/bin/env python3
"""Publish a website release: to test (test.multimc.org), or to production (multimc.org).

    website-publish.py [--config FILE] [--dry-run] [--no-purge] [release]
    website-publish.py [--config FILE] [--dry-run] [--no-purge] --production [release]

Test: the release (default: the newest releasable website release in RELEASES_DIR) goes to
WEBSITE_TEST_TARGET. hopper does this for every new commit on WEBSITE_BRANCH.

--production: the release on test (default; RELEASES_DIR/website-test.live names it) goes to
WEBSITE_TARGET, so production gets exactly the files checked on test. Run by hand.

The bucket becomes an exact copy of the release's site/ (rclone sync: new and changed files
uploaded, files not in the release removed), then the release's URLs and those of removed
files are purged from Cloudflare's cache, and RELEASES_DIR/website-<test|production>.live
records which release is live there (the release cleanup keeps those). One publish at a
time.
"""

import argparse
import json
from pathlib import Path

import common

log = common.logger("website")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-purge", action="store_true")
    parser.add_argument("release", nargs="?", type=Path)
    args = parser.parse_args()
    common.stop_on_sigterm()

    settings = common.load_settings(args.config)
    releases = Path(settings["RELEASES_DIR"])
    where = "production" if args.production else "test"
    target = settings["WEBSITE_TARGET" if args.production else "WEBSITE_TEST_TARGET"]
    url = settings["WEBSITE_URL" if args.production else "WEBSITE_TEST_URL"]
    marker = releases / ("website-%s.live" % where)

    with common.locked(releases / "website-publish.lock", "another website publish is running"):
        release = args.release.resolve() if args.release else default_release(releases, args.production)
        manifest = read_manifest(release)
        before = live_files(releases, marker)
        removed = sorted(set(before) - set(manifest["files"]))
        log("%s: %s (%s, %d files) -> %s (%s)" % (where, release.name, manifest["commit"][:10],
                                                  len(manifest["files"]), target, url))

        common.rclone(settings, "sync", *(["--dry-run"] if args.dry_run else []), "/site", target,
                      mount=(str(release / "site"), "/site"))
        if not args.no_purge:
            paths = sorted(set(manifest["files"]) | set(removed))
            urls = [url.rstrip("/") + "/" + p for p in paths]
            urls += [url.rstrip("/") + "/" + p[:-len("index.html")] for p in paths if p.endswith("index.html")]
            log("Cloudflare: purging %d URLs under %s (%d removed files)" % (len(urls), url, len(removed)))
            common.purge_cache(settings, urls, args.dry_run, "the site is published; publish again to retry")
        if args.dry_run:
            return
        new = marker.with_name(marker.name + ".new")
        new.write_text(release.name + "\n")
        new.replace(marker)
    log("%s is live on %s" % (release.name, where))


def default_release(releases, production):
    if production:
        test = releases / "website-test.live"
        if not test.is_file():
            common.die("nothing is on test yet (%s); name the release to publish" % test)
        return releases / test.read_text().strip()
    found = sorted(p for p in releases.glob("website-*") if p.is_dir() and (p / "manifest.json").is_file()
                   and json.loads((p / "manifest.json").read_text()).get("releasable"))
    if not found:
        common.die("no releasable website release in %s (website-build.py)" % releases)
    return found[-1]


def read_manifest(release):
    path = release / "manifest.json"
    if not path.is_file():
        common.die("%s is not a release (no manifest.json)" % release)
    manifest = json.loads(path.read_text())
    if manifest.get("kind") != "website":
        common.die("%s is not a website release (kind %r)" % (release, manifest.get("kind")))
    if not manifest.get("releasable"):
        common.die("%s is not releasable (see its hugo.log)" % release)
    return manifest


def live_files(releases, marker):
    """The files of the release live there now, if it's still around (to purge removed ones)."""
    if not marker.is_file():
        return []
    path = releases / marker.read_text().strip() / "manifest.json"
    return json.loads(path.read_text())["files"] if path.is_file() else []


if __name__ == "__main__":
    main()
