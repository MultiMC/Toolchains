#!/usr/bin/env python3
"""hopper: moves releases through their stages: a commit becomes a release, goes into the
local files tree, and is published.

    hopper.py [--config FILE] watch [--once]
    hopper.py [--config FILE] release <stream> <commit>
    hopper.py [--config FILE] release patrons
    hopper.py [--config FILE] status

Streams, each a branch of a repository and the script that builds a release from it:
  launcher      LAUNCHER_BRANCH of LAUNCHER_REPO, built by release-build.py
  translations  TRANSLATIONS_BRANCH of TRANSLATIONS_REPO, built by translations-build.py
Scheduled jobs, with a cron-style schedule ("minute hour day-of-month month day-of-week",
see cron.py); a job runs once for the most recent scheduled time it hasn't handled, so after
the machine was off it runs once, not once per missed time:
  patrons       the Patreon credits, made by patrons-update.py on PATRONS_SCHEDULE (only
                with PATRONS_CONFIG set: one machine, production)
All of them then go through deploy.py and publish.py.

watch    every WATCH_INTERVAL seconds, look at the head of each stream's branch. A commit
         not handled yet goes through its build, deploy.py and publish.py, each step only
         if the one before it succeeded. --once: look once, then exit.
release  run the same steps for the given stream and commit, or scheduled job, now (e.g.
         to retry a failed one)
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
import datetime
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import common
import cron

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


@dataclass(frozen=True)
class Scheduled:
    name: str
    schedule_setting: str  # a cron-style schedule, this machine's time
    enabled_setting: str   # the job only runs where this setting isn't empty
    build_script: str

    def enabled(self, settings):
        return bool(settings[self.enabled_setting] and settings[self.schedule_setting])

    def latest(self, settings, now):
        """The most recent scheduled time at or before `now` (a datetime), as "YYYY-MM-DD HH:MM"."""
        moment = cron.Schedule(settings[self.schedule_setting]).latest(now)
        return moment.strftime("%Y-%m-%d %H:%M") if moment else None


SCHEDULED = {j.name: j for j in [
    Scheduled("patrons", "PATRONS_SCHEDULE", "PATRONS_CONFIG", "patrons-update.py"),
]}
JOBS = {**STREAMS, **SCHEDULED}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="settings file overriding defaults.env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("watch").add_argument("--once", action="store_true")
    release = commands.add_parser("release")
    release.add_argument("job", choices=JOBS)
    release.add_argument("commit", nargs="?")
    commands.add_parser("status")
    args = parser.parse_args()

    if args.command == "release" and (args.job in STREAMS) != bool(args.commit):
        parser.error("a stream needs a commit, a scheduled job none")
    common.stop_on_sigterm()
    config = args.config.resolve() if args.config else None
    settings = common.load_settings(config)
    state = State(Path(settings["HOPPER_STATE"]))
    if args.command == "status":
        state.print()
        return

    with common.locked(str(state.path) + ".lock", "another hopper uses %s" % state.path):
        state.interrupt_stale()
        if args.command == "release" and args.job in STREAMS:
            run_pipeline(config, state, STREAMS[args.job], {"commit": args.commit})
        elif args.command == "release":
            job = SCHEDULED[args.job]
            if not job.enabled(settings):
                common.die("%s isn't enabled with these settings (%s)" % (args.job, job.enabled_setting))
            run_pipeline(config, state, job, {"scheduled": time.strftime("%Y-%m-%d %H:%M"), "by_hand": True})
        elif args.once:
            look(settings, config, state)
        else:
            watch(settings, config, state)


class State:
    """HOPPER_STATE: {stream or scheduled job: [entry, ...]}, each oldest first. An entry is written when its
    run starts and updated after every step, so a crash leaves it as "running". (A state
    from before translations, {"commits": [...]}, is read as the launcher stream's.)"""

    def __init__(self, path):
        self.path = path
        self.logs = Path(str(path) + ".logs")
        data = json.loads(path.read_text()) if path.exists() else {}
        if "commits" in data:
            data = {"launcher": data["commits"]}
        self.streams = {name: data.get(name, []) for name in JOBS}

    def entries(self):
        return [(name, entry) for name, entries in self.streams.items() for entry in entries]

    def interrupt_stale(self):
        """Entries still "running" when no hopper holds the lock are left over from a hopper
        that was killed or crashed."""
        for name, entry in self.entries():
            if entry["status"] == "running":
                entry["status"] = "interrupted"
                log("%s %s was left running by a previous hopper; recorded as interrupted"
                    % (name, label(entry)))
        self.save()

    def handled(self, job, key, value):
        return any(entry.get(key) == value for entry in self.streams[job.name])

    def add(self, job, entry):
        self.streams[job.name].append(entry)
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
                entry["time"], name, label(entry), entry.get("build") or "",
                entry["status"] + (" (%s)" % entry["step"] if entry.get("step") else ""),
                entry.get("release") or ""))


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def label(entry):
    """What an entry is about: a commit (streams) or a scheduled time (scheduled jobs)."""
    return entry["commit"][:10] if "commit" in entry else entry["scheduled"].replace(" ", "T")


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
    for job in SCHEDULED.values():
        log("scheduled %s: %s" % (job.name, settings[job.schedule_setting] if job.enabled(settings)
                                  else "off (%s is empty)" % job.enabled_setting))
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
    """One look at every stream and scheduled job; handles at most one release each."""
    for stream in STREAMS.values():
        commit = head(settings, stream)
        if state.handled(stream, "commit", commit):
            continue
        if not state.streams[stream.name]:
            state.add(stream, {"commit": commit, "time": now(), "status": "adopted"})
            log("%s: first look, %s adopted as already released (not built)" % (stream.name, commit[:10]))
            continue
        if common.is_locked(common.RELEASE_LOCK):
            log("%s: new commit %s, but a release build is running; looking again later"
                % (stream.name, commit[:10]))
            continue
        run_pipeline(config, state, stream, {"commit": commit})

    for job in SCHEDULED.values():
        if not job.enabled(settings):
            continue
        scheduled = job.latest(settings, datetime.datetime.now())
        if scheduled is None or state.handled(job, "scheduled", scheduled):
            continue
        if common.is_locked(common.RELEASE_LOCK):
            log("%s: due (%s), but a release build is running; looking again later" % (job.name, scheduled))
            continue
        run_pipeline(config, state, job, {"scheduled": scheduled})


def run_pipeline(config, state, job, item):
    """The job's build, deploy.py, publish.py for `item` ({"commit": ...} or {"date": ...}),
    each only if the one before succeeded. Their output goes to one log file per run."""
    run = Run(config, state, job, item)
    try:
        run.steps()
    except BaseException:
        if run.entry["status"] != "published":  # stopped in the cleanup after it: still published
            run.finish("interrupted", "stopped during %s; not retried automatically" % run.entry["step"])
        else:
            run.entry.pop("step", None)
            run.state.save()
        raise
    finally:
        run.logf.close()


class Run:
    """One commit going through the steps, recorded in the state as it goes. The entry
    records the full commit from the release's manifest (`commit` may be abbreviated when
    given by hand)."""

    def __init__(self, config, state, job, item):
        self.config_args = ["--config", str(config)] if config else []
        self.state = state
        self.job = job
        state.logs.mkdir(parents=True, exist_ok=True)
        self.entry = {**item, "time": now(), "status": "running", "step": "build"}
        self.logfile = state.logs / ("%s-%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), job.name, label(self.entry)))
        self.logf = open(self.logfile, "w")
        self.entry["log"] = str(self.logfile)
        state.add(job, self.entry)
        log("%s: releasing %s (log: %s)" % (job.name, label(self.entry), self.logfile))

    def steps(self):
        build_args = [self.entry["commit"]] if "commit" in self.entry else []
        status, output = self.step("build", self.job.build_script, *build_args, stdout=subprocess.PIPE)
        self.logf.write(output)
        release = output.strip().splitlines()[-1] if output.strip() else None
        if release:
            self.record_release(release)
        if status:
            return self.finish("failed", "build failed, nothing deployed")

        if self.step("deploy", "deploy.py", release, stdout=self.logf)[0]:
            return self.finish("failed", "deploy failed, nothing published")
        if self.step("publish", "publish.py", stdout=self.logf)[0]:
            return self.finish("failed", "publish failed")
        what = "build %s" % self.entry["build"] if self.entry.get("build") else os.path.basename(release)
        self.finish("published", "%s published" % what)
        # Housekeeping, not part of the release: a failure is only logged
        if self.step("cleanup", "releases.py", "cleanup", stdout=self.logf)[0]:
            log("%s %s: the release cleanup failed (see %s)" % (self.job.name, label(self.entry), self.logfile))
        self.entry.pop("step", None)
        self.state.save()

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
            if "commit" in manifest:
                self.entry["commit"] = manifest["commit"]
            if "build_number" in manifest:
                self.entry["build"] = manifest["build_number"]
        self.state.save()

    def finish(self, status, message):
        self.entry["status"] = status
        if status == "published":
            self.entry.pop("step")
        self.state.save()
        log("%s %s: %s (log: %s)" % (self.job.name, label(self.entry), message, self.logfile))


if __name__ == "__main__":
    main()
