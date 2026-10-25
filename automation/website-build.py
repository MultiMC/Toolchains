#!/usr/bin/env python3
"""Build a website release: the Website repo's Hugo site, in its image.

    website-build.py [--config FILE] [--out DIR] [commit]

1. Updates a local mirror of WEBSITE_REPO (state/website.git) and checks out WEBSITE_BRANCH
   at the commit (default: its head) into the release directory.
2. Runs `hugo -s site/` there in IMAGE_SITE (Hugo 0.31.1, TeamCity's image), without
   network, as the calling user; the site goes to site/ in the release directory. The same
   output as TeamCity's builds, except the copyright year, which Hugo takes from the clock.
3. Writes manifest.json (kind "website", the commit, the files, releasable: Hugo succeeded
   and made index.html).

The release goes into RELEASES_DIR/website-<time>-<commit> (or --out DIR, which must be new
or empty). Standard output gets one line, the release directory; logging goes to standard
error. One release build at a time (shared with release-build.py). website-publish.py takes
it from there.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import common

log = common.logger("website")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--out", type=Path)
    parser.add_argument("commit", nargs="?")
    args = parser.parse_args()
    common.stop_on_sigterm()

    settings = common.load_settings(args.config)
    if not settings["WEBSITE_REPO"]:
        common.die("WEBSITE_REPO is empty: the website isn't built with these settings")
    branch = settings["WEBSITE_BRANCH"]

    with common.lock_release():
        log("updating mirror")
        common.update_mirror(settings["WEBSITE_REPO"], common.WEBSITE_MIRROR)
        commit = common.resolve_on_branch(common.WEBSITE_MIRROR, branch, args.commit)
        if args.out:
            out = args.out.resolve()
            if out.exists() and any(out.iterdir()):
                common.die("%s is not empty" % out)
        else:
            out = Path(settings["RELEASES_DIR"]) / ("website-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), commit[:10]))
        out.mkdir(parents=True, exist_ok=True)
        log("release directory %s" % out)
        print(out, flush=True)

        src = out / "src"
        log("checking out %s at %s" % (branch, commit))
        common.run("git", "clone", "-q", "--no-hardlinks", "-b", branch, common.WEBSITE_MIRROR, src)
        common.run("git", "-C", src, "reset", "-q", "--hard", commit)
        common.run("git", "-C", src, "submodule", "-q", "update", "--init", "--recursive")

        log("running hugo")
        site = out / "site"
        site.mkdir()
        command = common.container_run(settings) + ["--network", "none",
                   "-v", "%s:/src:ro" % src, "-v", "%s:/out" % site, "-w", "/src",
                   settings["IMAGE_SITE"], "hugo", "-s", "site/", "-d", "/out"]
        with open(out / "hugo.log", "w") as logfile:
            result = subprocess.run(command, stdout=logfile, stderr=subprocess.STDOUT)

        files = sorted(str(p.relative_to(site)) for p in site.rglob("*") if p.is_file())
        releasable = result.returncode == 0 and "index.html" in files
        manifest = {"kind": "website", "commit": commit, "branch": branch,
                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "files": files, "releasable": releasable}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if not releasable:
        common.die("hugo failed (see %s)" % (out / "hugo.log"))
    log("releasable: %d files from %s, see %s" % (len(files), commit[:10], out / "manifest.json"))


if __name__ == "__main__":
    main()
