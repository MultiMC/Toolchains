#!/usr/bin/env python3
"""hopper: moves releases through their stages: a commit becomes a release, goes into the
local files tree, and is published.

    hopper.py [--config FILE] watch [--once]
    hopper.py [--config FILE] release <stream> <commit>
    hopper.py [--config FILE] status

Streams, each a branch of a repository and the script that builds a release from it:
  launcher      LAUNCHER_BRANCH of LAUNCHER_REPO, built by release-build.py
  translations  TRANSLATIONS_BRANCH of TRANSLATIONS_REPO, built by translations-build.py
Both then go through deploy.py and publish.py.

watch    every WATCH_INTERVAL seconds, look at the head of each stream's branch. A commit
         not handled yet goes through its build, deploy.py and publish.py, each step only
         if the one before it succeeded. --once: look once, then exit.
release  run the same steps for the given stream and commit now (e.g. to retry a failed one)
status   what has been handled, newest first

hopper builds and publishes nothing itself: it runs the same scripts a person would, so
every step can still be run and inspected on its own. Each handled commit is recorded in
HOPPER_STATE (JSON), each run's output in HOPPER_STATE.logs/. A commit that fails is not
retried automatically; the next commit is handled normally. Stopping hopper (SIGTERM,
Ctrl-C) stops the step that is running and records the commit as interrupted; it isn't
retried automatically either. When a stream has no records yet, its current head is
recorded as adopted, not built: it is assumed to be released already. If a release build
is running (e.g. one started by hand), the look is skipped and repeated next time. One
hopper per state file.

Something like systemd only has to keep `hopper.py watch` running.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import common

log = common.logger("hopper")


@dataclass(frozen=True)
class Stream:
    name: str
    repo_setting: str
    branch_setting: str
    build_script: str


STREAMS = {s.name: s for s in [
    Stream("launcher", "LAUNCHER_REPO", "LAUNCHER_BRANCH", "release-build.py"),
    Stream("translations", "TRANSLATIONS_REPO", "TRANSLATIONS_BRANCH", "translations-build.py"),
]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="settings file overriding defaults.env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("watch").add_argument("--once", action="store_true")
    release = commands.add_parser("release")
    release.add_argument("stream", choices=STREAMS)
    release.add_argument("commit")
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
            run_pipeline(config, state, STREAMS[args.stream], args.commit)
        elif args.once:
            look(settings, config, state)
        else:
            watch(settings, config, state)


class State:
    """HOPPER_STATE: {stream: [entry, ...]}, each oldest first. An entry is written when its
    run starts and updated after every step, so a crash leaves it as "running". (A state
    from before translations, {"commits": [...]}, is read as the launcher stream's.)"""

    def __init__(self, path):
        self.path = path
        self.logs = Path(str(path) + ".logs")
        data = json.loads(path.read_text()) if path.exists() else {}
        if "commits" in data:
            data = {"launcher": data["commits"]}
        self.streams = {name: data.get(name, []) for name in STREAMS}

    def entries(self):
        return [(name, entry) for name, entries in self.streams.items() for entry in entries]

    def interrupt_stale(self):
        """Entries still "running" when no hopper holds the lock are left over from a hopper
        that was killed or crashed."""
        for name, entry in self.entries():
            if entry["status"] == "running":
                entry["status"] = "interrupted"
                log("%s %s was left running by a previous hopper; recorded as interrupted"
                    % (name, entry["commit"][:10]))
        self.save()

    def handled(self, stream, commit):
        return any(entry["commit"] == commit for entry in self.streams[stream.name])

    def add(self, stream, entry):
        self.streams[stream.name].append(entry)
        self.save()
        return entry

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = Path(str(self.path) + ".new")
        new.write_text(json.dumps(self.streams, indent=2) + "\n")
        os.replace(new, self.path)

    def print(self):
        for name, entry in sorted(self.entries(), key=lambda item: item[1]["time"], reverse=True):
            print("%s  %-12s %s  %-6s %-22s %s" % (
                entry["time"], name, entry["commit"][:10], entry.get("build") or "",
                entry["status"] + (" (%s)" % entry["step"] if entry.get("step") else ""),
                entry.get("release") or ""))


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def head(settings, stream):
    """The commit at the head of the stream's branch."""
    repo, branch = settings[stream.repo_setting], settings[stream.branch_setting]
    line = common.output("git", "ls-remote", repo, "refs/heads/" + branch)
    if not line:
        common.die("%s has no branch %s" % (repo, branch))
    return line.split()[0]


def watch(settings, config, state):
    interval = int(settings["WATCH_INTERVAL"])
    for stream in STREAMS.values():
        log("watching %s: %s %s" % (stream.name, settings[stream.repo_setting], settings[stream.branch_setting]))
    log("every %d s" % interval)
    while True:
        try:
            look(settings, config, state)
        except common.Stopped:
            raise
        except SystemExit:
            log("this look failed (see above); trying again in %d s" % interval)
        time.sleep(interval)


def look(settings, config, state):
    """One look at every stream; handles at most one commit per stream."""
    for stream in STREAMS.values():
        commit = head(settings, stream)
        if state.handled(stream, commit):
            continue
        if not state.streams[stream.name]:
            state.add(stream, {"commit": commit, "time": now(), "status": "adopted"})
            log("%s: first look, %s adopted as already released (not built)" % (stream.name, commit[:10]))
            continue
        if common.is_locked(common.RELEASE_LOCK):
            log("%s: new commit %s, but a release build is running; looking again later"
                % (stream.name, commit[:10]))
            continue
        run_pipeline(config, state, stream, commit)


def run_pipeline(config, state, stream, commit):
    """The stream's build, deploy.py, publish.py for `commit`, each only if the one before
    succeeded. Their output goes to one log file per run."""
    run = Run(config, state, stream, commit)
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

    def __init__(self, config, state, stream, commit):
        self.config_args = ["--config", str(config)] if config else []
        self.state = state
        self.stream = stream
        state.logs.mkdir(parents=True, exist_ok=True)
        self.logfile = state.logs / ("%s-%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), stream.name, commit[:10]))
        self.logf = open(self.logfile, "w")
        self.entry = state.add(stream, {"commit": commit, "time": now(), "status": "running", "step": "build",
                                        "log": str(self.logfile)})
        log("%s: releasing %s (log: %s)" % (stream.name, commit[:10], self.logfile))

    def steps(self):
        status, output = self.step("build", self.stream.build_script, self.entry["commit"], stdout=subprocess.PIPE)
        self.logf.write(output)
        release = output.strip().splitlines()[-1] if output.strip() else None
        if release:
            self.record_release(release)
        if status:
            return self.finish("failed", "build failed, nothing deployed")

        if self.step("deploy", "deploy.py", release, stdout=self.logf)[0]:
            return self.finish("failed", "deploy failed, nothing published")
        if self.step("publish", "publish.py", release, stdout=self.logf)[0]:
            return self.finish("failed", "publish failed")
        what = "build %s" % self.entry["build"] if self.entry.get("build") else os.path.basename(release)
        self.finish("published", "%s published" % what)

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
            self.entry["commit"] = manifest["commit"]
            if "build_number" in manifest:
                self.entry["build"] = manifest["build_number"]
        self.state.save()

    def finish(self, status, message):
        self.entry["status"] = status
        if status == "published":
            self.entry.pop("step")
        self.state.save()
        log("%s %s: %s (log: %s)" % (self.stream.name, self.entry["commit"][:10], message, self.logfile))


if __name__ == "__main__":
    main()
