#!/usr/bin/env python3
"""What hopper and meta are doing on this machine, gathered from their files and systemd.

    overview.py [--json]

For every setup (each settings file next to this script but defaults.env: production,
files2), from its files: whether its hopper runs (the pid holding HOPPER_STATE's lock) and what it
last saw (HOPPER_STATE.status), its service (hopper@<setup>), each job's last run, what's
live (the published snapshot, the update channels, the website), and its runs, newest
first. For the machine: whether a release build runs (the pid holding its lock), the Toolchains checkout's commit,
free space, and meta's service and timer.

It only reads: run it any time, as the user hopper runs as. Without --json, a short text
summary; hopper-top.py shows the same live. The JSON is what other views read.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import common
import hopper

RUNS = 100  # the newest runs listed per setup

TIME = "%Y-%m-%d %H:%M:%S"


def gather():
    return {
        "time": time.strftime(TIME),
        "host": socket.gethostname(),
        "code": git_describe(common.TOOLCHAINS),
        "release_build": common.lock_holder(common.RELEASE_LOCK),
        "disk": disk(common.STATE),
        "setups": [setup(path) for path in setup_files()],
        "meta": {"service": unit("meta.service"), "timer": unit("meta.timer", "NextElapseUSecRealtime", "LastTriggerUSec")},
    }


def setup_files():
    files = [p for p in common.AUTOMATION.glob("*.env") if p.name != common.DEFAULTS.name]
    return sorted(files, key=lambda p: (p.stem != "production", p.stem))


def setup(path):
    settings = common.load_settings(path)
    state_path = Path(settings["HOPPER_STATE"])
    entries = json.loads(state_path.read_text()) if state_path.is_file() else {}
    status = read_json(Path(str(state_path) + ".status"))
    runs = sorted(((name, e) for name, es in entries.items() if name in hopper.JOBS for e in es),
                  key=lambda item: item[1]["time"], reverse=True)
    return {
        "name": path.stem,
        "config": str(path),
        "running": common.lock_holder(str(state_path) + ".lock"),
        "service": unit("hopper@%s.service" % path.stem),
        "status": status,
        "log": str(state_path) + ".logs/hopper.log",
        "jobs": [job_summary(settings, job, entries.get(job.name, []), (status or {}).get("jobs", {}).get(job.name))
                 for job in hopper.JOBS.values()],
        "live": live(settings),
        "runs": [run_summary(name, e) for name, e in runs[:RUNS]],
    }


def job_summary(settings, job, entries, seen):
    stream = job.name in hopper.STREAMS
    summary = {
        "name": job.name,
        "kind": "stream" if stream else "scheduled",
        "enabled": job.enabled(settings),
        "source": ("%s %s" % (settings[job.repo_setting], settings[job.branch_setting]) if stream
                   else settings[job.schedule_setting]),
        "seen": seen,
        "last": run_summary(job.name, entries[-1]) if entries else None,
        "last_published": next((run_summary(job.name, e) for e in reversed(entries) if e["status"] == "published"), None),
    }
    if stream and seen and seen.get("head"):
        summary["head_handled"] = any(e.get("commit") == seen["head"] for e in entries)
    return summary


def run_summary(job, entry):
    """A state entry, with its job, a label, and how long it took (so far). Entries from
    before hopper recorded step times end when their log was last written."""
    steps = entry.get("steps", [])
    end = entry.get("finished") or (steps[-1].get("end") if steps else None)
    if entry["status"] == "running":
        end = time.strftime(TIME)
    elif not end and entry.get("log") and os.path.isfile(entry["log"]):
        end = time.strftime(TIME, time.localtime(os.path.getmtime(entry["log"])))
    return {**entry, "job": job, "label": hopper.label(entry),
            "release": os.path.basename(entry["release"]) if entry.get("release") else None,
            "seconds": seconds_between(entry["time"], end) if end else None}


def live(settings):
    """What this setup has published: its files tree's last published snapshot, the newest
    version in each update channel ({channel: {version id: [platforms]}}), the website."""
    snapshot = common.published_marker(settings)
    name = snapshot.read_text().strip() if snapshot.is_file() else None
    info = read_json(common.snapshots_dir(settings) / (name + ".json")) if name else None
    channels = {}
    for index in sorted(Path(settings["FILES_ROOT"], "update").glob("*/*/index.json")):
        try:
            versions = common.channel_versions(index.read_text())
        except (ValueError, KeyError):
            continue
        if versions:
            newest = max(versions, key=lambda v: int(v["Id"]) if v["Id"].isdigit() else 0)
            channels.setdefault(index.parent.name, {}).setdefault(newest["Id"], []).append(index.parent.parent.name)
    releases = Path(settings["RELEASES_DIR"])
    return {
        "published": {"snapshot": name, **(info or {})} if name else None,
        "channels": channels,
        "website": {m.stem.split("-", 1)[1]: m.read_text().strip() for m in sorted(releases.glob("website-*.live"))},
    }


def unit(name, *properties):
    """A systemd user unit's state, times as local "YYYY-MM-DD HH:MM:SS" (null: never)."""
    properties = properties or ("ActiveState", "SubState", "Result", "UnitFileState", "ActiveEnterTimestamp",
                                "InactiveEnterTimestamp", "ExecMainStartTimestamp", "ExecMainExitTimestamp",
                                "ExecMainStatus", "NRestarts", "MainPID")
    result = subprocess.run(["systemctl", "--user", "show", name, "--timestamp=unix", "-p", ",".join(properties)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    values = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if value.startswith("@") and value[1:].isdigit():
            value = time.strftime(TIME, time.localtime(int(value[1:])))
        elif value.isdigit():
            value = int(value)
        values[key] = value if value != "" else None
    return values


def disk(path):
    usage = shutil.disk_usage(path)
    return {"path": str(path), "free": usage.free, "total": usage.total}


def git_describe(path):
    return subprocess.run(["git", "-C", str(path), "describe", "--always", "--dirty"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip() or None


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def seconds_between(start, end):
    return int(time.mktime(time.strptime(end, TIME)) - time.mktime(time.strptime(start, TIME)))


def duration(seconds):
    if seconds is None:
        return ""
    if seconds < 3600:
        return "%dm%02ds" % divmod(seconds, 60)
    return "%dh%02dm" % (seconds // 3600, seconds % 3600 // 60)


def short_time(text):
    """ "2026-10-27 12:00:06" -> "10-27 12:00" """
    return text[5:16] if text else ""


def print_text(data):
    print("%s  %s  code %s%s" % (data["host"], data["time"], data["code"],
                                 "  (a release build is running)" if data["release_build"] else ""))
    for s in data["setups"]:
        service = s["service"]
        print("\n%s: hopper %s, service %s/%s, %s restarts" % (
            s["name"], "running" if s["running"] else "not running", service.get("ActiveState"),
            service.get("UnitFileState"), service.get("NRestarts")))
        for job in s["jobs"]:
            last = job["last"]
            print("  %-13s %-4s %-26s %s" % (job["name"], "" if job["enabled"] else "off", job["source"].split()[-1] if job["kind"] == "stream" else job["source"],
                                             "%s %s %s %s" % (short_time(last["time"]), last["label"], last["status"], duration(last["seconds"])) if last else "-"))
    meta = data["meta"]["service"]
    print("\nmeta: last run %s, %s (exit %s), next %s" % (meta.get("ExecMainStartTimestamp"), meta.get("Result"),
                                                         meta.get("ExecMainStatus"), data["meta"]["timer"].get("NextElapseUSecRealtime")))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="everything, as JSON")
    args = parser.parse_args()
    data = gather()
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print_text(data)


if __name__ == "__main__":
    main()
