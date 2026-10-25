"""Shared parts of the build automation: settings, platforms, logging, locking, commands."""

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

AUTOMATION = Path(__file__).resolve().parent
TOOLCHAINS = AUTOMATION.parent
STATE = AUTOMATION / "state"
DEFAULTS = AUTOMATION / "defaults.env"


# --- platforms ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Platform:
    name: str
    image_setting: str   # the setting naming its toolchain image
    script: str          # its build steps in build/, run inside the image
    bundle: str          # the top directory of its install tree
    archive: str         # the download package format: "tar.gz" or "zip"

    def package(self, branch):
        """The download package's name, as TeamCity's deploy named it."""
        return "mmc-%s-%s.%s" % (branch, self.name, self.archive)


PLATFORMS = {p.name: p for p in [
    Platform("lin64", "IMAGE_LIN64", "linux.sh", "MultiMC", "tar.gz"),
    Platform("lin32", "IMAGE_LIN32", "linux.sh", "MultiMC", "tar.gz"),
    Platform("win32", "IMAGE_WIN32", "win32.sh", "MultiMC", "zip"),
    Platform("osx64-5.15.2", "IMAGE_OSX64", "osx64.sh", "MultiMC.app", "tar.gz"),
]}


def platform(name):
    if name not in PLATFORMS:
        die("unknown platform %s (known: %s)" % (name, " ".join(PLATFORMS)))
    return PLATFORMS[name]


# --- settings ----------------------------------------------------------------------------
#
# defaults.env lists every setting with its default. A config file (--config) overrides
# some of them, the environment overrides both. Both files are KEY=value lines; values may
# be quoted and may use $TOOLCHAINS, $HOME and settings defined before them.

SETTING_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")


def read_env_file(path, known):
    """Parse a KEY=value file; `known` gives the values $VARIABLES can refer to."""
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = SETTING_LINE.match(line)
        if not match:
            die("%s:%d: expected KEY=value" % (path, number))
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        def expand(m):
            name = m.group(1) or m.group(2)
            scope = {**known, **values}
            if name not in scope:
                die("%s:%d: unknown variable $%s" % (path, number, name))
            return scope[name]
        values[key] = VARIABLE.sub(expand, value)
    return values


class Settings(dict):
    """The settings, by name. `defaults` keeps the values from defaults.env."""

    def __init__(self, values, defaults):
        super().__init__(values)
        self.defaults = defaults

    def platforms(self):
        return [platform(name) for name in self["PLATFORMS"].split()]


def load_settings(config_file=None):
    base = {"TOOLCHAINS": str(TOOLCHAINS), "HOME": os.environ.get("HOME", "")}
    defaults = read_env_file(DEFAULTS, base)
    values = dict(defaults)
    if config_file:
        if not Path(config_file).is_file():
            die("config file not found: %s" % config_file)
        overrides = read_env_file(config_file, {**base, **defaults})
        unknown = sorted(set(overrides) - set(defaults))
        if unknown:
            die("%s: unknown settings %s (all settings are in defaults.env)" % (config_file, " ".join(unknown)))
        values.update(overrides)
    for key in defaults:
        if key in os.environ:
            values[key] = os.environ[key]
    return Settings(values, defaults)


# --- output and commands -----------------------------------------------------------------

def logger(tool):
    def log(message):
        print("[%s %s] %s" % (time.strftime("%H:%M:%S"), tool, message), file=sys.stderr, flush=True)
    return log


def die(message):
    print("error: %s" % message, file=sys.stderr)
    sys.exit(1)


def run(*args, **kwargs):
    """Run a command; stop with an error if it fails."""
    kwargs.setdefault("check", True)
    try:
        return subprocess.run([str(a) for a in args], **kwargs)
    except subprocess.CalledProcessError as e:
        die("command failed (exit %d): %s" % (e.returncode, " ".join(e.cmd)))


def output(*args):
    """Run a command and return its output, stripped."""
    return run(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


class Stopped(SystemExit):
    """Raised by SIGTERM once stop_on_sigterm() is in effect."""


def stop_on_sigterm():
    """Turn SIGTERM (what a service manager sends) into an exception, like Ctrl-C already is,
    so `with` blocks and `finally` clauses run and child processes can be stopped."""
    def handler(signum, frame):
        raise Stopped(128 + signum)
    signal.signal(signal.SIGTERM, handler)


def stop(processes, timeout=60):
    """Ask child processes to stop (SIGTERM; `docker run` passes it on to its container) and
    wait for them; kill whatever is still running after `timeout` seconds."""
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def container_run(settings):
    """The start of a command that runs a container: CONTAINER_ENGINE's `run`, removed
    afterwards, with an init process (it passes SIGTERM on to the command, which as process 1
    would ignore it, and ends the container with it), as the calling user, HOME=/tmp.
    docker: -u <uid>:<gid>. podman (rootless): --userns=keep-id, so the calling user is the
    same user inside, and files written to bind mounts belong to it."""
    engine = settings["CONTAINER_ENGINE"]
    if engine == "docker":
        as_user = ["-u", user()]
    elif engine == "podman":
        as_user = ["--userns=keep-id"]
    else:
        die("CONTAINER_ENGINE must be docker or podman, not %r" % engine)
    return [engine, "run", "--rm", "--init", *as_user, "-e", "HOME=/tmp"]


def image_exists(settings, image):
    return subprocess.run([settings["CONTAINER_ENGINE"], "image", "inspect", image],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def user():
    return "%d:%d" % (os.getuid(), os.getgid())


@contextmanager
def locked(path, busy):
    """Hold an exclusive lock on `path` (a lock file) for the duration of a `with` block.
    If someone else holds it, stop with the message `busy`. The lock goes away with the
    process, however it ends."""
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die("%s (locked: %s)" % (busy, path))
        yield


# --- repositories ------------------------------------------------------------------------

def update_mirror(url, path):
    """A local mirror of the repository at `url` (cloned if needed, its origin set to `url`,
    fetched); returns its path."""
    path = Path(path)
    if not path.is_dir():
        logger("git")("cloning mirror of %s" % url)
        run("git", "clone", "-q", "--mirror", url, path)
    run("git", "-C", path, "remote", "set-url", "origin", url)
    run("git", "-C", path, "fetch", "-q", "--prune", "origin")
    return path


def resolve_on_branch(mirror, branch, commit=None):
    """The full commit for `commit` (default: the head of `branch`) in the mirror; it must be
    on `branch`."""
    resolved = subprocess.run(["git", "-C", str(mirror), "rev-parse", "--verify", "-q",
                               "%s^{commit}" % (commit or "refs/heads/" + branch)],
                              stdout=subprocess.PIPE, text=True).stdout.strip()
    if not resolved:
        die("no commit %s in %s" % (commit, mirror))
    if subprocess.run(["git", "-C", str(mirror), "merge-base", "--is-ancestor", resolved,
                       "refs/heads/" + branch]).returncode:
        die("%s is not on %s" % (resolved, branch))
    return resolved


LAUNCHER_MIRROR = STATE / "launcher.git"
TRANSLATIONS_MIRROR = STATE / "translations.git"


# --- builds ------------------------------------------------------------------------------

def is_locked(path):
    """Whether someone holds the lock on `path` right now (for skipping, not for safety)."""
    if not Path(path).exists():
        return False
    with open(path) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


RELEASE_LOCK = STATE / "release-build.lock"


def lock_release():
    """One release build at a time: they share the Launcher mirror and the build counter,
    and each one uses every CPU anyway."""
    STATE.mkdir(exist_ok=True)
    return locked(RELEASE_LOCK, "another release build is running")


def lock_build_output(out):
    """One build at a time into a platform's output directory (it must exist)."""
    return locked(Path(out) / ".lock", "another build is using %s" % out)


def next_build_number(settings):
    """Take the next build number from BUILD_COUNTER, a file holding the last number used,
    and record it there before returning it. The caller holds the release lock. A number is
    never handed out twice, even if the build using it fails."""
    counter = Path(settings["BUILD_COUNTER"])
    if not counter.is_file():
        die("no build counter at %s; seed it with the last build number used "
            "(echo <number> > %s)" % (counter, counter))

    last = counter.read_text().strip()
    if not last.isdigit():
        die("%s should hold a number, not %r" % (counter, last))

    number = int(last) + 1
    new = counter.with_name(counter.name + ".new")
    with open(new, "w") as f:
        f.write("%d\n" % number)
        f.flush()
        os.fsync(f.fileno())
    os.replace(new, counter)
    return number


def build_command(settings, plat, src, out, build_number):
    """The docker command that builds one platform. The same for every platform: its image,
    an init process (--init: passes SIGTERM on to the build script, which as process 1
    would ignore it, and ends the container with it), no network, as the calling user, source at /src (read-only), output at /out, the build
    steps (build/) at /build (read-only), every setting plus PLATFORM and BUILD_NUMBER in the
    environment, command `bash /build/<script>`. The images contain only toolchains."""
    env = {**settings, "PLATFORM": plat.name, "BUILD_NUMBER": str(build_number)}
    command = container_run(settings) + ["--network", "none",
               "-v", "%s:/src:ro" % src, "-v", "%s:/out" % out,
               "-v", "%s:/build:ro" % (AUTOMATION / "build")]
    for key, value in env.items():
        command += ["-e", "%s=%s" % (key, value)]
    return command + [settings[plat.image_setting], "bash", "/build/" + plat.script]


# --- the files tree (files.multimc.org) --------------------------------------------------

def lock_files(settings):
    """Lock the local files tree (FILES_ROOT) for the duration of a `with` block."""
    root = Path(settings["FILES_ROOT"])
    return locked(str(root) + ".lock", "%s is in use by another script" % root)


def pull_files(settings, dry_run=False):
    """Make FILES_ROOT an exact copy of FILES_ORIGIN (rsync --delete), after a snapshot.
    A tree that doesn't exist yet is created as a subvolume."""
    root = Path(settings["FILES_ROOT"])
    if not settings["FILES_ORIGIN"]:
        die("no FILES_ORIGIN: %s is the only copy, nothing to pull" % root)

    root.parent.mkdir(parents=True, exist_ok=True)
    with lock_files(settings):
        if dry_run:
            run("rsync", "-a", "--delete", "--dry-run", "--info=stats1,name1",
                settings["FILES_ORIGIN"], str(root) + "/")
            return

        if root.exists():
            snapshot_files(settings, "before-pull", kind="before-pull", about="before pulling " + settings["FILES_ORIGIN"])
        else:
            run("btrfs", "subvolume", "create", root, stdout=subprocess.DEVNULL)
        run("rsync", "-a", "--delete", "--info=stats1", settings["FILES_ORIGIN"], str(root) + "/")
        mark_published(settings, "pulled", about="pulled from " + settings["FILES_ORIGIN"])


# Snapshots: FILES_ROOT is a btrfs subvolume; read-only snapshots of it are kept next to it
# in FILES_ROOT.snapshots/<time>-<label>. They share unchanged data with the tree, so they
# cost roughly what changed. Taking them needs no root; see files-snapshots.py.

def snapshots_dir(settings):
    return Path(settings["FILES_ROOT"] + ".snapshots")


def is_subvolume(path):
    """On btrfs, the top directory of a subvolume is always inode 256. (`btrfs subvolume show`
    would need root.)"""
    path = Path(path)
    if not path.is_dir() or path.stat().st_ino != 256:
        return False
    return output("stat", "-f", "-c", "%T", path) == "btrfs"


def snapshot_files(settings, label, kind="manual", about=""):
    """Take a read-only snapshot of FILES_ROOT (the caller holds its lock); return its path.
    Stops if FILES_ROOT isn't a subvolume: nothing changes the tree without a snapshot. Its
    metadata goes next to it, in <snapshot>.json: when, what kind (deploy, published,
    pulled, before-pull, before-restore, init, manual) and what about."""
    root = Path(settings["FILES_ROOT"])
    if not is_subvolume(root):
        die("%s is not a btrfs subvolume, so it can't be snapshotted (files-snapshots.py init)" % root)

    directory = snapshots_dir(settings)
    directory.mkdir(exist_ok=True)
    snapshot = directory / ("%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), label))
    run("btrfs", "subvolume", "snapshot", "-r", root, snapshot, stdout=subprocess.DEVNULL)
    info = {"created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "about": about}
    Path(str(snapshot) + ".json").write_text(json.dumps(info, indent=2) + "\n")
    return snapshot


# Snapshot kinds that record a state that was live (kept longer by the cleanup).
IMPORTANT_KINDS = ("published", "pulled")


def snapshot_info(snapshot):
    """A snapshot's metadata. Snapshots from before metadata existed: read from the name."""
    meta = Path(str(snapshot) + ".json")
    if meta.is_file():
        info = json.loads(meta.read_text())
    else:
        label = snapshot.name[16:]
        kind = ("deploy" if label.startswith(("before-deploy", "before-translations", "before-patrons"))
                else label if label in ("published", "pulled", "before-pull", "before-restore", "init")
                else "manual")
        info = {"kind": kind, "about": ""}
    info["time"] = time.mktime(time.strptime(snapshot.name[:15], "%Y%m%d-%H%M%S"))
    return info


def remove_snapshot(settings, snapshot):
    """Delete a snapshot and its metadata. Without root, btrfs only lets the owner delete a
    subvolume that is writable and empty. The snapshot recorded as published can't be
    removed: it is what publish.py compares with."""
    marker = published_marker(settings)
    if marker.is_file() and marker.read_text().strip() == snapshot.name:
        die("%s is the last published state (%s); it can't be removed" % (snapshot.name, marker))
    run("btrfs", "property", "set", snapshot, "ro", "false")
    for entry in snapshot.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    snapshot.rmdir()
    Path(str(snapshot) + ".json").unlink(missing_ok=True)


def cleanup_snapshots(settings, dry_run=False):
    """Remove old snapshots, like snapper's number cleanup: keep the one recorded as published,
    the newest SNAPSHOTS_KEEP_PUBLISHED published or pulled ones, the newest SNAPSHOTS_KEEP
    others, and anything younger than SNAPSHOTS_MIN_AGE_HOURS. Returns the removed names."""
    directory = snapshots_dir(settings)
    if not directory.is_dir():
        return []
    marker = published_marker(settings)
    current = marker.read_text().strip() if marker.is_file() else None
    snapshots = sorted(p for p in directory.iterdir() if p.is_dir())
    infos = {p: snapshot_info(p) for p in snapshots}
    important = [p for p in snapshots if infos[p]["kind"] in IMPORTANT_KINDS]
    others = [p for p in snapshots if infos[p]["kind"] not in IMPORTANT_KINDS]
    keep = set(important[-int(settings["SNAPSHOTS_KEEP_PUBLISHED"]):] if int(settings["SNAPSHOTS_KEEP_PUBLISHED"]) else [])
    keep |= set(others[-int(settings["SNAPSHOTS_KEEP"]):] if int(settings["SNAPSHOTS_KEEP"]) else [])
    young = time.time() - float(settings["SNAPSHOTS_MIN_AGE_HOURS"]) * 3600
    removed = []
    for p in snapshots:
        if p in keep or p.name == current or infos[p]["time"] > young:
            continue
        removed.append(p.name)
        if not dry_run:
            remove_snapshot(settings, p)
    return removed


def channel_versions(index):
    """The version list of a channel's index.json (text); IDs are strings, older ones numbers."""
    return [{**v, "Id": str(v["Id"])} for v in json.loads(index)["Versions"]]


# What changed between two trees, as {path: {"old": sha256, "new": sha256}} (null: the file
# didn't exist / doesn't any more).

def sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_files(root):
    """{relative path: os.stat_result} for the regular files (not symlinks) under root."""
    found = {}
    for directory, _, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            if not os.path.islink(path):
                found[os.path.relpath(path, root)] = os.stat(path)
    return found


def tree_changes(before, after):
    """The files that differ between two trees (a snapshot and the tree it was taken of).
    A snapshot keeps inode numbers, so a file with the same inode, size and modification
    time is unchanged; only the others are hashed."""
    old, new = regular_files(before), regular_files(after)
    changes = {}
    for path in sorted(set(old) | set(new)):
        a, b = old.get(path), new.get(path)
        if a and b and (a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_ino, b.st_size, b.st_mtime_ns):
            continue
        old_hash = sha256_file(os.path.join(before, path)) if a else None
        new_hash = sha256_file(os.path.join(after, path)) if b else None
        if old_hash != new_hash:
            changes[path] = {"old": old_hash, "new": new_hash}
    return changes


# What was last published: FILES_ROOT.published names the snapshot of the tree as it was at
# the last successful publish (or pull, which makes the tree equal to the live one).
# publish.py publishes the difference between that snapshot and the tree, whatever
# deploys made it, then records a new one.

def published_marker(settings):
    return Path(settings["FILES_ROOT"] + ".published")


def published_snapshot(settings):
    marker = published_marker(settings)
    if not marker.is_file():
        die("nothing records what was last published (%s); files-pull.py records the live state" % marker)
    snapshot = snapshots_dir(settings) / marker.read_text().strip()
    if not is_subvolume(snapshot):
        die("the last published snapshot %s is missing" % snapshot)
    return snapshot


def mark_published(settings, label, about=""):
    """Snapshot the tree and record it as what is live now (the caller holds the tree's lock)."""
    snapshot = snapshot_files(settings, label, kind=label, about=about)
    marker = published_marker(settings)
    new = Path(str(marker) + ".new")
    new.write_text(snapshot.name + "\n")
    os.replace(new, marker)
    return snapshot


# --- releases ----------------------------------------------------------------------------

def read_release(release_dir):
    """The manifest of a release made by release-build.py; it must be releasable."""
    manifest = json.loads((Path(release_dir) / "manifest.json").read_text())
    if not manifest.get("releasable"):
        die("%s is not releasable (see its manifest.json)" % release_dir)
    return manifest
