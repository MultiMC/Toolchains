#!/usr/bin/env python3
"""Build, package and verify a Launcher release for all platforms. Deploys nothing.

    release-build.py [--config FILE] [--incremental [--clean]] [--build-number N] [--out DIR] [commit]

--config      settings file overriding defaults.env (environment overrides both)
--incremental reuse a persistent source checkout and per-platform build trees in
              state/work (for development). The checkout is updated with git, so only
              changed files get new timestamps; CMake configure runs every time.
--clean       with --incremental: start the persistent build trees from scratch
--build-number
              use N instead of the next number from the build counter (BUILD_COUNTER),
              which is then left alone; for test builds
--out         put the release in DIR, which must be new or empty. Default:
              RELEASES_DIR/<build number>, or <build number>.2, .3, ... if a test build
              (--build-number) already used that number there
commit        a commit on LAUNCHER_BRANCH (default: its current head)

Steps: update the local Launcher mirror (state/launcher.git), check out the branch (as a
branch, so the commit and refs/heads/<branch> get embedded) at the commit, build PLATFORMS
in parallel in their toolchain containers, package them like TeamCity's deploy did, run
compat-check.py against the descriptions in GATE_DESCRIPTIONS, write manifest.json.
Exit status 0 only if every build and every compatibility check passed.

The build number (Launcher_VERSION_BUILD) must keep increasing for the updater. Without
--build-number it is the next one from BUILD_COUNTER, taken (and recorded) only once
everything that can stop the build before it starts is fine: the commit is on the branch,
the toolchain images and the gate's descriptions are there, the source is checked out (prepared in
RELEASES_DIR/.preparing-<pid>, renamed to the build number after). A build that fails
after that uses up its number. One release build runs at a time.

Standard output gets exactly one line, the release directory, as soon as it exists (also
when the build later fails); all logging goes to standard error. So:
./deploy.py "$(./release-build.py)"
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path

import common

log = common.logger("release")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--build-number", type=int)
    parser.add_argument("--out", type=Path)
    parser.add_argument("commit", nargs="?")
    args = parser.parse_args()
    common.stop_on_sigterm()
    if args.clean and not args.incremental:
        parser.error("--clean only makes sense with --incremental")

    settings = common.load_settings(args.config)
    branch = settings["LAUNCHER_BRANCH"]
    platforms = settings.platforms()

    with common.lock_release():
        # Everything that can stop the build before it starts happens before a build number
        # is taken: the commit, the images, the descriptions, the output directory, the checkout.
        commit = resolve_commit(settings, branch, args.commit)
        check_prerequisites(settings, platforms)
        if args.out:
            prepared = args.out.resolve()
            if prepared.exists() and any(prepared.iterdir()):
                common.die("%s is not empty" % prepared)
        else:
            # Left over by a run that was killed (-9): with the release lock held, none is in use.
            for stale in Path(settings["RELEASES_DIR"]).glob(".preparing-*"):
                shutil.rmtree(stale)
            prepared = Path(settings["RELEASES_DIR"]) / (".preparing-%d" % os.getpid())
        prepared.mkdir(parents=True, exist_ok=True)

        if args.incremental:
            work = common.STATE / "work"
            work.mkdir(exist_ok=True)
            src = work / "src"
            settings["CLEAN"] = "1" if args.clean else "0"
        else:
            src = prepared / "src"
            settings["CLEAN"] = "1"
        try:
            checkout(branch, commit, src)
        except BaseException:
            if not args.out:
                shutil.rmtree(prepared)
            raise

        if args.build_number is None:
            build_number = common.next_build_number(settings)
            log("build number %d (from %s)" % (build_number, settings["BUILD_COUNTER"]))
        else:
            build_number = args.build_number
            log("build number %d (given; the counter is left alone)" % build_number)

        out = prepared
        if not args.out:
            out = release_dir(settings, build_number)
            prepared.rename(out)
            if not args.incremental:
                src = out / "src"
        log("release directory %s" % out)
        # The only thing on standard output (logging goes to standard error), so callers
        # can use it: ./deploy.py "$(./release-build.py)"
        print(out, flush=True)
        build_root = common.STATE / "work" / "build" if args.incremental else out / "build"

        build(settings, platforms, src, build_root, out, build_number)
        package(platforms, branch, build_root, out)
        passed = gate(settings, platforms, src, build_root, out)
        write_manifest(settings, platforms, branch, commit, build_number, args.incremental,
                       src, build_root, out, passed)

    if not all(passed.values()):
        log("NOT RELEASABLE: compatibility check failed for %s" % " ".join(p for p, ok in passed.items() if not ok))
        sys.exit(1)
    log("releasable: build %d of %s, see %s" % (build_number, commit, out / "manifest.json"))


def release_dir(settings, build_number):
    """RELEASES_DIR/<build number>; a test build reusing a number gets <number>.2, .3, ..."""
    releases = Path(settings["RELEASES_DIR"])
    candidate, n = releases / str(build_number), 1
    while candidate.exists():
        n += 1
        candidate = releases / ("%d.%d" % (build_number, n))
    return candidate


def resolve_commit(settings, branch, commit):
    """Update the Launcher mirror (state/launcher.git); the full commit for `commit` (default:
    the head of `branch`), which must be on `branch`."""
    log("updating mirror")
    common.update_mirror(settings["LAUNCHER_REPO"], common.LAUNCHER_MIRROR)
    return common.resolve_on_branch(common.LAUNCHER_MIRROR, branch, commit)


def check_prerequisites(settings, platforms):
    """The toolchain images, and the descriptions the compatibility gate checks against."""
    for p in platforms:
        image = settings[p.image_setting]
        if not common.image_exists(settings, image):
            common.die("toolchain image %s (%s) isn't there; build or load it (../containers/)" % (image, p.name))
        description = Path(settings["GATE_DESCRIPTIONS"]) / ("%s.toml" % p.name)
        if not description.is_file():
            common.die("the gate's description %s is missing" % description)


def checkout(branch, commit, src):
    """Check out `branch` at `commit` (from the mirror) in `src`, with submodules."""
    path = common.LAUNCHER_MIRROR
    log("checking out %s at %s" % (branch, commit))
    git = ["git", "-C", src]
    if not (src / ".git").is_dir():
        common.run("git", "clone", "-q", "--no-hardlinks", "-b", branch, path, src)
    else:
        # Persistent checkout: only files that actually change get touched (and new mtimes).
        # Its origin is the mirror, wherever this directory is now.
        common.run(*git, "remote", "set-url", "origin", path)
        common.run(*git, "fetch", "-q", "origin")
        common.run(*git, "checkout", "-q", "-B", branch, commit)
    common.run(*git, "reset", "-q", "--hard", commit)
    common.run(*git, "clean", "-q", "-ffdx")
    common.run(*git, "submodule", "-q", "sync", "--recursive")
    common.run(*git, "submodule", "-q", "update", "--init", "--recursive")
    common.run(*git, "submodule", "-q", "foreach", "--recursive", "git clean -q -ffdx")


def build(settings, platforms, src, build_root, out, build_number):
    """Build every platform in parallel, each logging to build-<platform>.log."""
    log("building %s (CLEAN=%s)" % (" ".join(p.name for p in platforms), settings["CLEAN"]))
    running = {}
    failed = []
    with ExitStack() as locks:
        for p in platforms:
            (build_root / p.name).mkdir(parents=True, exist_ok=True)
            locks.enter_context(common.lock_build_output(build_root / p.name))
            command = common.build_command(settings, p, src, build_root / p.name, build_number)
            with open(out / ("build-%s.log" % p.name), "w") as logfile:
                running[p.name] = subprocess.Popen(command, stdout=logfile, stderr=subprocess.STDOUT)

        try:
            for name, process in running.items():
                if process.wait() == 0:
                    log("  %s: built" % name)
                else:
                    log("  %s: BUILD FAILED (see build-%s.log)" % (name, name))
                    failed.append(name)
        except BaseException:
            log("stopping the platform builds")
            common.stop(running.values())
            raise
    if failed:
        common.die("build failed: %s" % " ".join(failed))


def package(platforms, branch, build_root, out):
    """packages/: the downloads, as TeamCity's deploy named them (mmc-<branch>-<platform>,
    .tar.gz or .zip). deploy/<platform>.tar.gz: the bundle with its permissions, which
    deploy.py hands to repoman (TeamCity's package.tar.gz)."""
    (out / "packages").mkdir()
    (out / "deploy").mkdir()
    for p in platforms:
        install = build_root / p.name / "install"
        with tarfile.open(out / "deploy" / ("%s.tar.gz" % p.name), "w:gz") as tar:
            tar.add(install / p.bundle, arcname=p.bundle)
        target = out / "packages" / p.package(branch)
        if p.archive == "zip":
            write_zip(install, p.bundle, target)
        else:
            target.write_bytes((out / "deploy" / ("%s.tar.gz" % p.name)).read_bytes())


def write_zip(root, top, target):
    """Zip root/top as top/..., like `python -m zipfile -c` (the VM's zips had no permissions)."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(root / top, top)
        for dirpath, dirnames, filenames in os.walk(root / top):
            dirnames.sort()
            for name in sorted(dirnames) + sorted(filenames):
                path = Path(dirpath) / name
                z.write(path, path.relative_to(root))


def gate(settings, platforms, src, build_root, out):
    """Check each platform's build against its description (compat-check.py); {platform: passed}."""
    descriptions = Path(settings["GATE_DESCRIPTIONS"])
    log("compatibility checks against %s" % descriptions)
    # URLs in the descriptions can be ${SETTING}: each gets this build's value, if the
    # Launcher being built can take it (its CMakeLists.txt has Launcher_<setting>);
    # otherwise the production default, which such a Launcher has hard-coded.
    cmake = (src / "CMakeLists.txt").read_text()
    values = []
    for key in ("UPDATER_BASE", "NOTIFICATION_URL", "TRANSLATIONS_BASE_URL"):
        value = settings[key] if ("Launcher_" + key) in cmake else settings.defaults[key]
        values += ["--set", "%s=%s" % (key, value)]
    passed = {}
    for p in platforms:
        tree = build_root / p.name / "install" / p.bundle
        with open(out / ("compat-%s.txt" % p.name), "w") as report:
            result = subprocess.run([sys.executable, common.AUTOMATION / "compat-check.py", "check", p.name, tree,
                                     descriptions / ("%s.toml" % p.name),
                                     "--json", out / ("compat-%s.json" % p.name)] + values, stdout=report)
        passed[p.name] = result.returncode == 0
        for line in (out / ("compat-%s.txt" % p.name)).read_text().splitlines():
            print("    " + line, file=sys.stderr)
    return passed


def version_name(src):
    """major.minor.hotfix from the Launcher's CMakeLists.txt (what TeamCity's tcversion printed)."""
    text = (src / "CMakeLists.txt").read_text()
    parts = [re.search(r"^set\(Launcher_VERSION_%s\s+(\d+)\)" % part, text, re.M) for part in ("MAJOR", "MINOR", "HOTFIX")]
    if not all(parts):
        common.die("can't read the version from %s" % (src / "CMakeLists.txt"))
    return ".".join(m.group(1) for m in parts)


def write_manifest(settings, platforms, branch, commit, build_number, incremental, src, build_root, out, passed):
    manifest = {
        "commit": commit,
        "branch": branch,
        "build_number": build_number,
        "version_name": version_name(src),
        "mode": "incremental" if incremental else "clean",
        "updater_base": settings["UPDATER_BASE"],
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platforms": {},
    }
    for p in platforms:
        package = out / "packages" / p.package(branch)
        data = package.read_bytes()
        gate_result = json.loads((out / ("compat-%s.json" % p.name)).read_text())
        manifest["platforms"][p.name] = {
            "package": package.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "install_tree": str(build_root / p.name / "install"),
            "deploy_archive": "deploy/%s.tar.gz" % p.name,
            "compat_passed": gate_result["passed"],
            "compat_problems": gate_result["problems"],
        }
    manifest["releasable"] = all(passed.values())
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
