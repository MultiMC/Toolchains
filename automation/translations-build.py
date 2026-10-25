#!/usr/bin/env python3
"""Build a translations release: the Translations repo's release.py, in its image.

    translations-build.py [--config FILE] [--out DIR] [commit]

1. Updates a local mirror of TRANSLATIONS_REPO (state/translations.git) and checks out
   TRANSLATIONS_BRANCH at the commit (default: its head) into the release directory.
2. Runs release.py there in IMAGE_TRANSLATIONS, without network, as the calling user. A
   language whose .po can't be used keeps its previous release, taken from the local files
   tree's translations/index_v2.json (FILES_ROOT), not from the live site.
3. Writes manifest.json (kind "translations", the commit, the files, releasable).

The release goes into RELEASES_DIR/translations-<time>-<commit> (or --out DIR, which must
be new or empty). Standard output gets one line, the release directory; logging goes to
standard error. One release build at a time (shared with release-build.py).
deploy.py and publish.py take it from there.
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import common

log = common.logger("translations")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--out", type=Path)
    parser.add_argument("commit", nargs="?")
    args = parser.parse_args()
    common.stop_on_sigterm()

    settings = common.load_settings(args.config)
    branch = settings["TRANSLATIONS_BRANCH"]
    previous = Path(settings["FILES_ROOT"]) / "translations" / "index_v2.json"

    with common.lock_release():
        commit = resolve_commit(settings, branch, args.commit)
        if args.out:
            out = args.out.resolve()
            if out.exists() and any(out.iterdir()):
                common.die("%s is not empty" % out)
        else:
            out = Path(settings["RELEASES_DIR"]) / ("translations-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), commit[:10]))
        out.mkdir(parents=True, exist_ok=True)
        log("release directory %s" % out)
        print(out, flush=True)

        src = out / "src"
        log("checking out %s at %s" % (branch, commit))
        common.run("git", "clone", "-q", "--no-hardlinks", "-b", branch, common.TRANSLATIONS_MIRROR, src)
        common.run("git", "-C", src, "reset", "-q", "--hard", commit)

        log("running release.py (previous index: %s)" % (previous if previous.is_file() else "none"))
        command = common.container_run(settings) + ["--network", "none",
                   "-e", "PYTHONDONTWRITEBYTECODE=1",
                   "-v", "%s:/src:ro" % src, "-v", "%s:/out" % out, "-w", "/src"]
        if previous.is_file():
            command += ["-v", "%s:/previous/index_v2.json:ro" % previous]
        command += [settings["IMAGE_TRANSLATIONS"], "python3", "release.py", "--output", "/out/build",
                    "--previous-index", "/previous/index_v2.json"]
        with open(out / "release.log", "w") as logfile:
            result = subprocess.run(command, stdout=logfile, stderr=subprocess.STDOUT)

        build = out / "build"
        built = sorted(os.listdir(build)) if build.is_dir() else []
        releasable = result.returncode == 0 and "index_v2.json" in built
        manifest = {"kind": "translations", "commit": commit, "branch": branch,
                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "files": built, "releasable": releasable}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if not releasable:
        common.die("release.py failed (see %s)" % (out / "release.log"))
    log("releasable: %d files from %s, see %s" % (len(built), commit[:10], out / "manifest.json"))


def resolve_commit(settings, branch, commit):
    """Update the Translations mirror (state/translations.git); the full commit for `commit`
    (default: the head of `branch`), which must be on `branch`."""
    log("updating mirror")
    common.update_mirror(settings["TRANSLATIONS_REPO"], common.TRANSLATIONS_MIRROR)
    return common.resolve_on_branch(common.TRANSLATIONS_MIRROR, branch, commit)


if __name__ == "__main__":
    main()
