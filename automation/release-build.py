#!/usr/bin/env python3
"""Build, package and verify a Launcher release for all platforms. Deploys nothing.

    release-build.py [--config FILE] [--incremental [--clean]] <build number> <out dir> [commit]

--config      settings file overriding defaults.env (environment overrides both)
--incremental reuse a persistent source checkout and per-platform build trees in
              state/work (for development). The checkout is updated with git, so only
              changed files get new timestamps; CMake configure runs every time.
--clean       with --incremental: start the persistent build trees from scratch
build number  Launcher_VERSION_BUILD; must keep increasing for the updater
out dir       new, empty directory for this release
commit        a commit on LAUNCHER_BRANCH (default: its current head)

Steps: update the local Launcher mirror (state/launcher.git), check out the branch (as a
branch, so the commit and refs/heads/<branch> get embedded) at the commit, build PLATFORMS
in parallel in their toolchain containers, package them like TeamCity's deploy did, run
compat-check.py against BASELINES, write manifest.json.
Exit status 0 only if every build and every compatibility check passed.
"""

import argparse
import hashlib
import json
import os
import re
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
    parser.add_argument("build_number", type=int)
    parser.add_argument("out", type=Path)
    parser.add_argument("commit", nargs="?")
    args = parser.parse_args()
    if args.clean and not args.incremental:
        parser.error("--clean only makes sense with --incremental")

    settings = common.load_settings(args.config)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        common.die("%s is not empty" % out)
    out.mkdir(parents=True, exist_ok=True)
    common.STATE.mkdir(exist_ok=True)

    with ExitStack() as stack:
        if args.incremental:
            work = common.STATE / "work"
            work.mkdir(exist_ok=True)
            stack.enter_context(common.locked(work / ".lock", "another incremental build"))
            src, build_root = work / "src", work / "build"
            settings["CLEAN"] = "1" if args.clean else "0"
        else:
            src, build_root = out / "src", out / "build"
            settings["CLEAN"] = "1"

        branch = settings["LAUNCHER_BRANCH"]
        commit = checkout(settings, branch, args.commit, src)
        platforms = settings.platforms()
        build(settings, platforms, src, build_root, out, args.build_number)
        package(platforms, branch, build_root, out)
        passed = gate(settings, platforms, build_root, out)
        write_manifest(settings, platforms, branch, commit, args, src, build_root, out, passed)

    if not all(passed.values()):
        log("NOT RELEASABLE: compatibility check failed for %s" % " ".join(p for p, ok in passed.items() if not ok))
        sys.exit(1)
    log("releasable: build %d of %s, see %s" % (args.build_number, commit, out / "manifest.json"))


def checkout(settings, branch, commit, src):
    """Update the mirror and check out `branch` at `commit` in `src`; return the commit."""
    mirror = common.STATE / "launcher.git"
    if not mirror.is_dir():
        log("cloning mirror of %s" % settings["LAUNCHER_REPO"])
        common.run("git", "clone", "-q", "--mirror", settings["LAUNCHER_REPO"], mirror)
    log("updating mirror")
    common.run("git", "-C", mirror, "fetch", "-q", "--prune", "origin")
    commit = common.output("git", "-C", mirror, "rev-parse", "--verify",
                           "%s^{commit}" % (commit or "refs/heads/" + branch))
    if subprocess.run(["git", "-C", mirror, "merge-base", "--is-ancestor", commit, "refs/heads/" + branch]).returncode:
        common.die("%s is not on %s" % (commit, branch))

    log("checking out %s at %s" % (branch, commit))
    git = ["git", "-C", src]
    if not (src / ".git").is_dir():
        common.run("git", "clone", "-q", "--no-hardlinks", "-b", branch, mirror, src)
    else:
        # Persistent checkout: only files that actually change get touched (and new mtimes).
        # Its origin is the mirror, wherever this directory is now.
        common.run(*git, "remote", "set-url", "origin", mirror)
        common.run(*git, "fetch", "-q", "origin")
        common.run(*git, "checkout", "-q", "-B", branch, commit)
    common.run(*git, "reset", "-q", "--hard", commit)
    common.run(*git, "clean", "-q", "-ffdx")
    common.run(*git, "submodule", "-q", "sync", "--recursive")
    common.run(*git, "submodule", "-q", "update", "--init", "--recursive")
    common.run(*git, "submodule", "-q", "foreach", "--recursive", "git clean -q -ffdx")
    return commit


def build(settings, platforms, src, build_root, out, build_number):
    """Build every platform in parallel, each logging to build-<platform>.log."""
    log("building %s (CLEAN=%s)" % (" ".join(p.name for p in platforms), settings["CLEAN"]))
    running = {}
    for p in platforms:
        (build_root / p.name).mkdir(parents=True, exist_ok=True)
        command = common.build_command(settings, p, src, build_root / p.name, build_number)
        with open(out / ("build-%s.log" % p.name), "w") as logfile:
            running[p.name] = subprocess.Popen(command, stdout=logfile, stderr=subprocess.STDOUT)
    failed = []
    for name, process in running.items():
        if process.wait() == 0:
            log("  %s: built" % name)
        else:
            log("  %s: BUILD FAILED (see build-%s.log)" % (name, name))
            failed.append(name)
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


def gate(settings, platforms, build_root, out):
    """Run compat-check.py for each platform against the shipped build; {platform: passed}."""
    baselines = Path(settings["BASELINES"])
    log("compatibility checks against %s" % baselines.name)
    # The baselines embed the production URLs (the defaults); a build for another system
    # (e.g. files2.env) is checked against the baseline URLs mapped to its own.
    url_map = []
    for key in ("UPDATER_BASE", "NOTIFICATION_URL"):
        if settings[key] != settings.defaults[key]:
            url_map += ["--url-map", "%s=%s" % (settings.defaults[key], settings[key])]
    passed = {}
    for p in platforms:
        tree = build_root / p.name / "install" / p.bundle
        baseline = baselines / p.package("develop")
        with open(out / ("compat-%s.txt" % p.name), "w") as report:
            result = subprocess.run([sys.executable, common.AUTOMATION / "compat-check.py", p.name, tree, baseline,
                                     "--json", out / ("compat-%s.json" % p.name)] + url_map, stdout=report)
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


def write_manifest(settings, platforms, branch, commit, args, src, build_root, out, passed):
    manifest = {
        "commit": commit,
        "branch": branch,
        "build_number": args.build_number,
        "version_name": version_name(src),
        "mode": "incremental" if args.incremental else "clean",
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
