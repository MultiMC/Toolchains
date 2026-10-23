#!/usr/bin/env python3
"""Build one platform in its toolchain container. The same for every platform.

    run-build.py [--config FILE] <platform> <source dir> <output dir> [build number]

platform     lin64, lin32, win32 or osx64-5.15.2
source dir   a git checkout on its branch (not detached), with submodules, so the commit
             and branch get embedded like in the TeamCity builds
output dir   gets build/ (kept between runs unless CLEAN=1), install/, *.log
build number Launcher_VERSION_BUILD (default 9999)

How the container is run: see common.build_command.
"""

import argparse
import os
from pathlib import Path

import common


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    parser.add_argument("platform")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("build_number", nargs="?", type=int, default=9999)
    args = parser.parse_args()

    settings = common.load_settings(args.config)
    plat = common.platform(args.platform)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    command = common.build_command(settings, plat, args.source.resolve(), out, args.build_number)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
