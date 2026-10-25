#!/usr/bin/env python3
"""Compatibility gate: check a Launcher build against a description of what it must be.

    compat-check.py check <platform> <install tree> <description.toml> [--json out.json] [--set NAME=VALUE]...
    compat-check.py describe <platform> <install tree or package> [--source NAME]

<install tree> is the MultiMC/ or MultiMC.app/ directory; a package is a shipped .tar.gz or
.zip. The description (expectations/<platform>.toml) is edited by hand whenever the
Launcher changes on purpose: it says what the build must look like, so every change to the
gate conditions is visible and reviewed. `describe` writes one from an existing build, to
start from (it was used once, on the builds TeamCity shipped).

What a description holds, and what `check` does with it:
  [files]  list: exactly these files in the bundle (none more, none less)
  [urls]   main_binary: required: these URLs embedded in the main binary (a missing
           updater or notification URL would cut users off from updates). ${NAME} is
           replaced by the setting NAME, given with --set (release-build.py passes
           UPDATER_BASE, NOTIFICATION_URL and TRANSLATIONS_BASE_URL)
  [elf]    lin*: machine: every ELF has it; system_libs: the only libraries from outside
           the bundle they may need; max_versions: no GLIBC_/GLIBCXX_/CXXABI_/GCC_ symbol
           version newer than these
  [pe]     win32: machine: every PE has it (i386 = 332); max_os_version and
           max_subsystem_version (4.0 = XP); system_dlls: the only DLLs from outside the
           bundle they may import; [pe.sha256]: bundled files that must stay byte-identical
           (they come straight from the toolchain)
  [macho]  osx64*: archs: exactly these; max_minimum_macos; link_prefixes: libraries may
           only come from inside the bundle or these places

Exit status 0 = pass, 1 = fail. Needs objdump and llvm-otool on the host.
"""

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile

MAIN_BINARY = {"lin64": "bin/MultiMC", "lin32": "bin/MultiMC", "win32": "MultiMC.exe"}
URL_RE = re.compile(rb"https?://[\x21-\x7e]+?(?=[\x00\"'<>\s]|$)")

# Files we build ourselves; everything else in a Windows bundle comes from the toolchain.
WIN_OURS = re.compile(r"^(MultiMC\.exe|libLauncher_.*|jars/.*)$")
VERSION_PREFIXES = ("GLIBC_", "GLIBCXX_", "CXXABI_", "GCC_")
MACHINE_NAMES = {62: "x86_64", 3: "i386", 0x14C: "i386"}

# URLs that come from settings: `describe` writes them as ${NAME}...
URL_SETTINGS = {
    "UPDATER_BASE": "https://files.multimc.org/update/",
    "NOTIFICATION_URL": "https://files.multimc.org/notifications.json",
    "TRANSLATIONS_BASE_URL": "https://files.multimc.org/translations/",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("platform")
    check.add_argument("tree")
    check.add_argument("description")
    check.add_argument("--json")
    check.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    describe = commands.add_parser("describe")
    describe.add_argument("platform")
    describe.add_argument("build", help="install tree or shipped package")
    describe.add_argument("--source", help="what to call it in the header (default: its path)")
    args = parser.parse_args()

    if args.command == "describe":
        with tempfile.TemporaryDirectory() as tmp:
            root = args.build if os.path.isdir(args.build) else extract(args.build, tmp)
            sys.stdout.write(write_description(args.platform, files(root), args.source or args.build))
        return 0

    values = dict(item.split("=", 1) for item in args.set)
    with open(args.description, "rb") as f:
        expected = tomllib.load(f)
    problems, facts = check_build(args.platform, files(args.tree), expected, values)
    result = {"platform": args.platform, "description": os.path.basename(args.description),
              "passed": not problems, "problems": problems, "facts": facts}
    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, indent=2, sort_keys=True)
    print("%s: %s (%d files)" % (args.platform, "PASS" if not problems else "FAIL", facts["files"]))
    for key, value in sorted(facts.items()):
        if key != "files":
            print("    %s: %s" % (key, value))
    for problem in problems:
        print("  ! " + problem)
    return 0 if not problems else 1


# --- reading a build ---------------------------------------------------------------------

def run(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def files(root):
    """{relative path: full path} for every regular file (not symlinks) under root."""
    out = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                out[os.path.relpath(path, root).replace(os.sep, "/")] = path
    return out


def extract(package, tmp):
    if package.endswith(".zip"):
        zipfile.ZipFile(package).extractall(tmp)
    else:
        with tarfile.open(package) as t:
            t.extractall(tmp, filter="data")
    tops = [d for d in os.listdir(tmp) if not d.startswith(".")]
    if len(tops) != 1:
        sys.exit("%s: expected one top-level directory, got %s" % (package, tops))
    return os.path.join(tmp, tops[0])


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def elf_info(path):
    with open(path, "rb") as f:
        head = f.read(20)
    if head[:4] != b"\x7fELF":
        return None
    machine = struct.unpack_from("<H", head, 18)[0]
    needed = set(re.findall(r"NEEDED\s+(\S+)", run("objdump", "-p", path)))
    versions = {}
    for v in re.findall(r"\b((?:%s)[0-9.]+)" % "|".join(VERSION_PREFIXES), run("objdump", "-T", path)):
        prefix = v[:v.index("_") + 1]
        if prefix not in versions or vtuple(v) > vtuple(versions[prefix]):
            versions[prefix] = v
    return {"machine": machine, "needed": needed, "versions": versions}


def linux_summary(tree):
    machines, needed, versions = set(), set(), {}
    own = set(os.path.basename(p) for p in tree)
    for p in tree.values():
        info = elf_info(p)
        if not info:
            continue
        machines.add(info["machine"])
        needed |= {n for n in info["needed"] if n not in own}
        for prefix, v in info["versions"].items():
            if prefix not in versions or vtuple(v) > vtuple(versions[prefix]):
                versions[prefix] = v
    return machines, needed, versions


def pe_info(path):
    with open(path, "rb") as f:
        b = f.read(4096)
    if b[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[pe:pe + 4] != b"PE\0\0":
        return None
    machine = struct.unpack_from("<H", b, pe + 4)[0]
    opt = pe + 24
    os_ver = struct.unpack_from("<HH", b, opt + 40)
    sub_ver = struct.unpack_from("<HH", b, opt + 48)
    dlls = set(d.lower() for d in re.findall(r"DLL Name: (\S+)", run("objdump", "-p", path)))
    return {"machine": machine, "os": os_ver, "subsystem": sub_ver, "dlls": dlls}


def windows_summary(tree):
    machines, os_max, sub_max, imports = set(), (0, 0), (0, 0), set()
    own = set(os.path.basename(p).lower() for p in tree)
    for p in tree.values():
        info = pe_info(p)
        if not info:
            continue
        machines.add(info["machine"])
        os_max, sub_max = max(os_max, info["os"]), max(sub_max, info["subsystem"])
        imports |= {d for d in info["dlls"] if d not in own}
    return machines, os_max, sub_max, imports


def macho_info(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe"):
        return None
    header = run("llvm-otool", "-hv", path)
    archs = set(re.findall(r"\b(X86_64|I386|ARM64|ARM)\b", header))
    loads = run("llvm-otool", "-l", path)
    minos = [vtuple(m) for m in re.findall(r"(?:LC_VERSION_MIN_MACOSX[\s\S]*?\n\s+version|\n\s+minos) ([0-9.]+)", loads)]
    deps = [l.split()[0] for l in run("llvm-otool", "-L", path).splitlines()[1:] if l.strip()]
    return {"archs": archs, "minos": max(minos) if minos else None, "deps": deps}


def macos_summary(tree):
    archs, minos, deps = set(), (0,), []
    for rel, p in tree.items():
        info = macho_info(p)
        if not info:
            continue
        archs |= info["archs"]
        if info["minos"]:
            minos = max(minos, info["minos"])
        deps += [(rel, d) for d in info["deps"]]
    return archs, minos, deps


def embedded_urls(path):
    with open(path, "rb") as f:
        data = f.read()
    urls = set(m.group().decode("ascii", "replace") for m in URL_RE.finditer(data))
    # Windows/Qt also store strings as UTF-16LE: decode each such string on its own
    for run16 in re.finditer(rb"(?:[\x20-\x7e]\x00){8,}", data):
        text = run16.group()[::2]
        urls |= set(m.group().decode("ascii", "replace") for m in URL_RE.finditer(text))
    return urls


def main_binary(platform):
    return MAIN_BINARY.get(platform, "Contents/MacOS/MultiMC")


# --- check -------------------------------------------------------------------------------

def check_build(platform, tree, expected, values):
    problems, facts = [], {"files": len(tree)}

    listed = set(expected["files"]["list"])
    for rel in sorted(set(tree) - listed):
        problems.append("file not in the description: %s" % rel)
    for rel in sorted(listed - set(tree)):
        problems.append("missing file: %s" % rel)

    if platform in ("lin64", "lin32"):
        check_linux(tree, expected["elf"], problems, facts)
    elif platform == "win32":
        check_windows(tree, expected["pe"], problems, facts)
    elif platform.startswith("osx64"):
        check_macos(tree, expected["macho"], problems, facts)
    else:
        problems.append("unknown platform %s" % platform)

    check_urls(tree, expected["urls"], values, problems, facts)
    return problems, facts


def check_linux(tree, expected, problems, facts):
    machines, needed, versions = linux_summary(tree)
    facts.update(machines=sorted(machines), system_libs=sorted(needed), max_versions=versions)
    if machines != {expected["machine"]}:
        problems.append("ELF machine types %s, expected only %d" % (sorted(machines), expected["machine"]))
    for lib in sorted(needed - set(expected["system_libs"])):
        problems.append("needs a system library not in the description: %s" % lib)
    allowed = expected["max_versions"]
    for prefix, v in sorted(versions.items()):
        if prefix not in allowed:
            problems.append("needs %s symbols, the description allows none" % v)
        elif vtuple(v) > vtuple(allowed[prefix]):
            problems.append("needs %s, the description allows up to %s" % (v, allowed[prefix]))


def check_windows(tree, expected, problems, facts):
    machines, os_max, sub_max, imports = windows_summary(tree)
    facts.update(machines=sorted(machines), os_version="%d.%d" % os_max,
                 subsystem_version="%d.%d" % sub_max, system_dlls=sorted(imports))
    if machines != {expected["machine"]}:
        problems.append("PE machine types %s, expected only %d" % (sorted(machines), expected["machine"]))
    if os_max > vtuple(expected["max_os_version"]):
        problems.append("OS version %d.%d above %s" % (os_max + (expected["max_os_version"],)))
    if sub_max > vtuple(expected["max_subsystem_version"]):
        problems.append("subsystem version %d.%d above %s (XP is 4.0)" % (sub_max + (expected["max_subsystem_version"],)))
    for dll in sorted(imports - set(expected["system_dlls"])):
        problems.append("imports a system DLL not in the description: %s" % dll)
    for rel, digest in sorted(expected["sha256"].items()):
        if rel in tree and sha256(tree[rel]) != digest:
            problems.append("bundled file differs from the one described: %s" % rel)


def check_macos(tree, expected, problems, facts):
    archs, minos, deps = macos_summary(tree)
    facts.update(archs=sorted(archs), minimum_macos=".".join(map(str, minos)))
    if archs != set(expected["archs"]):
        problems.append("Mach-O architectures %s, expected %s" % (sorted(archs), expected["archs"]))
    if minos > vtuple(expected["max_minimum_macos"]):
        problems.append("minimum macOS %s above %s" % (".".join(map(str, minos)), expected["max_minimum_macos"]))
    for rel, dep in deps:
        if not dep.startswith(tuple(expected["link_prefixes"])):
            problems.append("links from outside the bundle and the allowed places: %s -> %s" % (rel, dep))


def check_urls(tree, expected, values, problems, facts):
    rel = expected["main_binary"]
    if rel not in tree:
        problems.append("main binary %s not found" % rel)
        return
    found = embedded_urls(tree[rel])
    facts["embedded_urls"] = len(found)
    for template in expected["required"]:
        url = re.sub(r"\$\{(\w+)\}", lambda m: values.get(m.group(1), URL_SETTINGS.get(m.group(1), m.group(0))), template)
        if url not in found:
            problems.append("URL missing from the main binary: %s" % url)


# --- describe ----------------------------------------------------------------------------

def toml_string(s):
    return json.dumps(s)


def toml_list(items, indent="    "):
    if not items:
        return "[]"
    return "[\n" + "".join("%s%s,\n" % (indent, toml_string(i)) for i in items) + "]"


def templated(url):
    """Write URLs that come from a setting as ${NAME}..., longest prefix first."""
    for name, prefix in sorted(URL_SETTINGS.items(), key=lambda kv: -len(kv[1])):
        if url.startswith(prefix):
            return "${%s}%s" % (name, url[len(prefix):])
    return url


def write_description(platform, tree, source):
    out = ["# What a %s build must look like; checked by compat-check.py (see its --help)." % platform,
           "# Generated on %s from %s, then edited by hand:" % (time.strftime("%Y-%m-%d"), source),
           "# change it together with the Launcher change that needs it, and say why.",
           "",
           "[files]",
           "list = " + toml_list(sorted(tree)),
           ""]

    if platform in ("lin64", "lin32"):
        machines, needed, versions = linux_summary(tree)
        (machine,) = machines
        out += ["[elf]",
                "machine = %d  # %s" % (machine, MACHINE_NAMES.get(machine, "?")),
                "system_libs = " + toml_list(sorted(needed)),
                "max_versions = { %s }" % ", ".join("%s = %s" % (toml_string(k), toml_string(v))
                                                    for k, v in sorted(versions.items())),
                ""]
    elif platform == "win32":
        machines, os_max, sub_max, imports = windows_summary(tree)
        (machine,) = machines
        out += ["[pe]",
                "machine = %d  # %s" % (machine, MACHINE_NAMES.get(machine, "?")),
                'max_os_version = "%d.%d"' % os_max,
                'max_subsystem_version = "%d.%d"  # 4.0 = Windows XP' % sub_max,
                "system_dlls = " + toml_list(sorted(imports)),
                "",
                "[pe.sha256]",
                "# Bundled files from the toolchain (Qt, MinGW runtime, OpenSSL, zlib): byte-identical"]
        out += ["%s = %s" % (toml_string(rel), toml_string(sha256(path)))
                for rel, path in sorted(tree.items()) if not WIN_OURS.match(rel)]
        out.append("")
    elif platform.startswith("osx64"):
        archs, minos, _ = macos_summary(tree)
        out += ["[macho]",
                "archs = " + toml_list(sorted(archs)),
                'max_minimum_macos = "%s"' % ".".join(map(str, minos)),
                'link_prefixes = ["@", "/usr/lib/", "/System/"]',
                ""]

    rel = main_binary(platform)
    out += ["[urls]",
            "main_binary = %s" % toml_string(rel),
            "# ${NAME} is the setting NAME (%s)" % ", ".join(URL_SETTINGS),
            "required = " + toml_list(sorted(templated(u) for u in embedded_urls(tree[rel]))),
            ""]
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
