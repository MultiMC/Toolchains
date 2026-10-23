"""Shared parts of the build automation: settings, platforms, logging, locking, commands."""

import fcntl
import json
import os
import re
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


def user():
    return "%d:%d" % (os.getuid(), os.getgid())


@contextmanager
def locked(path, what):
    """Hold an exclusive lock on `path` (a lock file); stop if someone else holds it."""
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die("%s is in use (%s)" % (what, path))
        yield


# --- builds ------------------------------------------------------------------------------

def build_command(settings, plat, src, out, build_number):
    """The docker command that builds one platform. The same for every platform: its image,
    no network, as the calling user, source at /src (read-only), output at /out, the build
    steps (build/) at /build (read-only), every setting plus PLATFORM and BUILD_NUMBER in the
    environment, command `bash /build/<script>`. The images contain only toolchains."""
    env = {**settings, "PLATFORM": plat.name, "BUILD_NUMBER": str(build_number)}
    command = ["docker", "run", "--rm", "--network", "none", "-u", user(), "-e", "HOME=/tmp",
               "-v", "%s:/src:ro" % src, "-v", "%s:/out" % out,
               "-v", "%s:/build:ro" % (AUTOMATION / "build")]
    for key, value in env.items():
        command += ["-e", "%s=%s" % (key, value)]
    return command + [settings[plat.image_setting], "bash", "/build/" + plat.script]


# --- the files tree (files.multimc.org) --------------------------------------------------

def lock_files(settings):
    """Lock the local files tree (FILES_ROOT) for the duration of a `with` block."""
    root = Path(settings["FILES_ROOT"])
    return locked(str(root) + ".lock", root)


def pull_files(settings, dry_run=False):
    """Make FILES_ROOT an exact copy of FILES_ORIGIN (rsync --delete)."""
    root = Path(settings["FILES_ROOT"])
    if not settings["FILES_ORIGIN"]:
        die("no FILES_ORIGIN: %s is the only copy, nothing to pull" % root)
    root.mkdir(parents=True, exist_ok=True)
    with lock_files(settings):
        options = ["--dry-run", "--info=stats1,name1"] if dry_run else ["--info=stats1"]
        run("rsync", "-a", "--delete", *options, settings["FILES_ORIGIN"], str(root) + "/")


def channel_versions(index):
    """The version list of a channel's index.json (text); IDs are strings, older ones numbers."""
    return [{**v, "Id": str(v["Id"])} for v in json.loads(index)["Versions"]]


# --- releases ----------------------------------------------------------------------------

def read_release(release_dir):
    """The manifest of a release made by release-build.py; it must be releasable."""
    manifest = json.loads((Path(release_dir) / "manifest.json").read_text())
    if not manifest.get("releasable"):
        die("%s is not releasable (see its manifest.json)" % release_dir)
    return manifest
