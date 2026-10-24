#!/usr/bin/env python3
"""hopper: moves Launcher builds through their stages: a commit becomes a release build,
goes into the local files tree, and is published.

    hopper.py [--config FILE] watch [--once]
    hopper.py [--config FILE] release <commit>
    hopper.py [--config FILE] status

watch    every WATCH_INTERVAL seconds, look at the head of LAUNCHER_BRANCH in LAUNCHER_REPO.
         A commit not handled yet goes through release-build.py, deploy.py and publish.py,
         each step only if the one before it succeeded. --once: look once, then exit.
release  run the same steps for the given commit now (e.g. to retry a failed one)
status   what has been handled, newest first

hopper builds and publishes nothing itself: it runs the same scripts a person would, so
every step can still be run and inspected on its own. Each handled commit is recorded in
HOPPER_STATE (JSON), each run's output in HOPPER_STATE.logs/. A commit that fails is not
retried automatically; the next commit is handled normally. Stopping hopper (SIGTERM,
Ctrl-C) stops the step that is running and records the commit as interrupted; it isn't
retried automatically either. On the first start (no state
yet) the current head is recorded as adopted, not built: it is assumed to be released
already. If a release build is running (e.g. one started by hand), the look is skipped and
repeated next time. One hopper per state file.

Something like systemd only has to keep `hopper.py watch` running.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import common

log = common.logger("hopper")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="settings file overriding defaults.env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("watch").add_argument("--once", action="store_true")
    commands.add_parser("release").add_argument("commit")
    commands.add_parser("status")
    args = parser.parse_args()

    common.stop_on_sigterm()
    config = args.config.resolve() if args.config else None
    settings = common.load_settings(config)
    state = State(Path(settings["HOPPER_STATE"]))
    if args.command == "status":
        state.print()
        return

    with common.locked(str(state.path) + ".lock", "another hopper uses %s" % state.path):
        state.interrupt_stale()
        if args.command == "release":
            run_pipeline(settings, config, state, args.commit)
        elif args.once:
            look(settings, config, state)
        else:
            watch(settings, config, state)


class State:
    """HOPPER_STATE: {"commits": [entry, ...]}, oldest first. An entry is written when its
    run starts and updated after every step, so a crash leaves it as "running"."""

    def __init__(self, path):
        self.path = path
        self.logs = Path(str(path) + ".logs")
        self.commits = json.loads(path.read_text())["commits"] if path.exists() else []

    def interrupt_stale(self):
        """Entries still "running" when no hopper holds the lock are left over from a hopper
        that was killed or crashed."""
        for entry in self.commits:
            if entry["status"] == "running":
                entry["status"] = "interrupted"
                log("%s was left running by a previous hopper; recorded as interrupted" % entry["commit"][:10])
        self.save()

    def handled(self, commit):
        return any(entry["commit"] == commit for entry in self.commits)

    def add(self, entry):
        self.commits.append(entry)
        self.save()
        return entry

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = Path(str(self.path) + ".new")
        new.write_text(json.dumps({"commits": self.commits}, indent=2) + "\n")
        os.replace(new, self.path)

    def print(self):
        for entry in reversed(self.commits):
            print("%s  %s  %-6s %-22s %s" % (entry["time"], entry["commit"][:10], entry.get("build") or "",
                                             entry["status"] + (" (%s)" % entry["step"] if entry.get("step") else ""),
                                             entry.get("release") or ""))


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def head(settings):
    """The commit at the head of LAUNCHER_BRANCH in LAUNCHER_REPO."""
    line = common.output("git", "ls-remote", settings["LAUNCHER_REPO"], "refs/heads/" + settings["LAUNCHER_BRANCH"])
    if not line:
        common.die("%s has no branch %s" % (settings["LAUNCHER_REPO"], settings["LAUNCHER_BRANCH"]))
    return line.split()[0]


def watch(settings, config, state):
    interval = int(settings["WATCH_INTERVAL"])
    log("watching %s %s every %d s" % (settings["LAUNCHER_REPO"], settings["LAUNCHER_BRANCH"], interval))
    while True:
        try:
            look(settings, config, state)
        except common.Stopped:
            raise
        except SystemExit:
            log("this look failed (see above); trying again in %d s" % interval)
        time.sleep(interval)


def look(settings, config, state):
    """One look at the branch; handles at most one commit."""
    commit = head(settings)
    if state.handled(commit):
        return
    if not state.commits:
        state.add({"commit": commit, "time": now(), "status": "adopted"})
        log("first start: %s adopted as already released (not built)" % commit[:10])
        return
    if common.is_locked(common.RELEASE_LOCK):
        log("new commit %s, but a release build is running; looking again later" % commit[:10])
        return
    run_pipeline(settings, config, state, commit)


def run_pipeline(settings, config, state, commit):
    """release-build.py, deploy.py, publish.py for `commit`, each only if the one before
    succeeded. Their output goes to one log file per run."""
    run = Run(config, state, commit)
    try:
        run.steps()
    except BaseException:
        run.finish("interrupted", "stopped during %s; not retried automatically" % run.entry["step"])
        raise
    finally:
        run.logf.close()


class Run:
    """One commit going through the steps, recorded in the state as it goes. The entry
    records the full commit from the release's manifest (`commit` may be abbreviated when
    given by hand)."""

    def __init__(self, config, state, commit):
        self.config_args = ["--config", str(config)] if config else []
        self.state = state
        state.logs.mkdir(parents=True, exist_ok=True)
        self.logfile = state.logs / ("%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), commit[:10]))
        self.logf = open(self.logfile, "w")
        self.entry = state.add({"commit": commit, "time": now(), "status": "running", "step": "build",
                                "log": str(self.logfile)})
        log("releasing %s (log: %s)" % (commit[:10], self.logfile))

    def steps(self):
        status, output = self.step("build", "release-build.py", self.entry["commit"], stdout=subprocess.PIPE)
        self.logf.write(output)
        release = output.strip().splitlines()[-1] if output.strip() else None
        if release:
            self.record_release(release)
        if status:
            return self.finish("failed", "release build failed, nothing deployed")

        if self.step("deploy", "deploy.py", release, stdout=self.logf)[0]:
            return self.finish("failed", "deploy failed, nothing published")
        if self.step("publish", "publish.py", release, stdout=self.logf)[0]:
            return self.finish("failed", "publish failed")
        self.finish("published", "build %s published" % self.entry["build"])

    def step(self, name, script, *args, stdout):
        """Run one script; returns (exit status, its standard output if stdout=PIPE). If
        hopper is stopped meanwhile, the script is stopped too."""
        self.entry["step"] = name
        self.state.save()
        self.logf.write("\n=== %s %s: %s %s\n" % (now(), name, script, " ".join(args)))
        self.logf.flush()
        process = subprocess.Popen([sys.executable, common.AUTOMATION / script, *self.config_args, *args],
                                   stdout=stdout, stderr=self.logf, text=True)
        try:
            output, _ = process.communicate()
        except BaseException:
            common.stop([process])
            raise
        return process.returncode, output

    def record_release(self, release):
        self.entry["release"] = release
        manifest = Path(release) / "manifest.json"
        if manifest.exists():
            manifest = json.loads(manifest.read_text())
            self.entry["commit"], self.entry["build"] = manifest["commit"], manifest["build_number"]
        self.state.save()

    def finish(self, status, message):
        self.entry["status"] = status
        if status == "published":
            self.entry.pop("step")
        self.state.save()
        log("%s: %s (log: %s)" % (self.entry["commit"][:10], message, self.logfile))


if __name__ == "__main__":
    main()
