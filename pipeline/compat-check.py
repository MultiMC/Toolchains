#!/usr/bin/env python3
"""Compatibility gate: compare a fresh Launcher build with the platform's baseline.

    compat-check.py <platform> <build dir> <baseline archive> [--json out.json]

<build dir> is the install tree root (the MultiMC/ or MultiMC.app/ directory).
<baseline archive> is a shipped package (../baselines/...): .tar.gz or .zip.

Checks, per platform:
  all     same file list as the baseline (a new or missing file fails until the
          baseline is deliberately updated)
  lin*    every ELF has the expected architecture; no system library needed that the
          baseline didn't need; no newer GLIBC_/GLIBCXX_/CXXABI_/GCC_ symbol versions
  win32   every PE is i386; subsystem/OS version not above the baseline (4.0 = XP); no
          system DLL imported that the baseline didn't import; bundled third-party DLLs
          byte-identical (they come straight from the toolchain)
  osx64*  every Mach-O is x86_64 only; minimum macOS not above the baseline (10.13);
          nothing linked from outside the bundle, /usr/lib or /System
  all     every URL embedded in the baseline's main binary is also in the new one (a
          missing updater or notification URL would cut users off from updates)

Exit status 0 = pass, 1 = fail. Needs objdump and llvm-otool on the host.
"""

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile

MAIN_BINARY = {"lin64": "bin/MultiMC", "lin32": "bin/MultiMC", "win32": "MultiMC.exe"}
URL_RE = re.compile(rb"https?://[\x21-\x7e]+?(?=[\x00\"'<>\s]|$)")

# Files we build ourselves; everything else in a Windows bundle comes from the toolchain.
WIN_OURS = re.compile(r"^(MultiMC\.exe|libLauncher_.*|jars/.*)$")
VERSION_PREFIXES = ("GLIBC_", "GLIBCXX_", "CXXABI_", "GCC_")


def run(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def files(root):
    out = {}
    for dirpath, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            if not os.path.islink(p):
                out[os.path.relpath(p, root)] = p
    return out


def extract_baseline(archive, tmp):
    if archive.endswith(".zip"):
        zipfile.ZipFile(archive).extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter="data")
    tops = [d for d in os.listdir(tmp) if not d.startswith(".")]
    if len(tops) != 1:
        sys.exit("baseline %s: expected one top-level directory, got %s" % (archive, tops))
    return os.path.join(tmp, tops[0])


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


# --- Linux -----------------------------------------------------------------------------

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
    for rel, p in tree.items():
        info = elf_info(p)
        if not info:
            continue
        machines.add(info["machine"])
        needed |= {n for n in info["needed"] if n not in own}
        for prefix, v in info["versions"].items():
            if prefix not in versions or vtuple(v) > vtuple(versions[prefix]):
                versions[prefix] = v
    return machines, needed, versions


def check_linux(platform, new, base, problems, facts):
    expected = {"lin64": 62, "lin32": 3}[platform]  # EM_X86_64, EM_386
    nm, nn, nv = linux_summary(new)
    bm, bn, bv = linux_summary(base)
    facts.update(machines=sorted(nm), system_libs=sorted(nn), max_versions=nv)
    if nm != {expected}:
        problems.append("ELF machine types %s, expected only %d" % (sorted(nm), expected))
    for lib in sorted(nn - bn):
        problems.append("needs system library not needed before: %s" % lib)
    for prefix, v in sorted(nv.items()):
        if prefix not in bv:
            problems.append("needs %s symbols, baseline needed none" % v)
        elif vtuple(v) > vtuple(bv[prefix]):
            problems.append("needs %s, baseline max was %s" % (v, bv[prefix]))


# --- Windows ---------------------------------------------------------------------------

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
    for rel, p in tree.items():
        info = pe_info(p)
        if not info:
            continue
        machines.add(info["machine"])
        os_max, sub_max = max(os_max, info["os"]), max(sub_max, info["subsystem"])
        imports |= {d for d in info["dlls"] if d not in own}
    return machines, os_max, sub_max, imports


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def check_windows(new, base, problems, facts):
    nm, nos, nsub, nimp = windows_summary(new)
    bm, bos, bsub, bimp = windows_summary(base)
    facts.update(machines=sorted(nm), os_version="%d.%d" % nos, subsystem_version="%d.%d" % nsub,
                 system_dlls=sorted(nimp))
    if nm != {0x14C}:
        problems.append("PE machine types %s, expected only i386 (0x14c)" % sorted(nm))
    if nos > bos:
        problems.append("OS version %d.%d above baseline %d.%d" % (nos + bos))
    if nsub > bsub:
        problems.append("subsystem version %d.%d above baseline %d.%d (XP is 4.0)" % (nsub + bsub))
    for dll in sorted(nimp - bimp):
        problems.append("imports system DLL not imported before: %s" % dll)
    for rel in sorted(set(new) & set(base)):
        if not WIN_OURS.match(rel.replace(os.sep, "/")) and sha256(new[rel]) != sha256(base[rel]):
            problems.append("bundled third-party file differs from baseline: %s" % rel)


# --- macOS -----------------------------------------------------------------------------

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
    archs, minos, outside = set(), (0,), []
    for rel, p in tree.items():
        info = macho_info(p)
        if not info:
            continue
        archs |= info["archs"]
        if info["minos"]:
            minos = max(minos, info["minos"])
        for d in info["deps"]:
            if not (d.startswith("@") or d.startswith("/usr/lib/") or d.startswith("/System/")):
                outside.append("%s -> %s" % (rel, d))
    return archs, minos, outside


def check_macos(new, base, problems, facts):
    na, nmin, nout = macos_summary(new)
    ba, bmin, _ = macos_summary(base)
    facts.update(archs=sorted(na), minimum_macos=".".join(map(str, nmin)))
    if na != {"X86_64"}:
        problems.append("Mach-O architectures %s, expected only X86_64" % sorted(na))
    if nmin > bmin:
        problems.append("minimum macOS %s above baseline %s" % (".".join(map(str, nmin)), ".".join(map(str, bmin))))
    for o in nout:
        problems.append("links outside the bundle and system: %s" % o)


def embedded_urls(path):
    data = open(path, "rb").read()
    urls = set(m.group().decode("ascii", "replace") for m in URL_RE.finditer(data))
    # Windows/Qt also store strings as UTF-16LE: decode each such string on its own
    for run16 in re.finditer(rb"(?:[\x20-\x7e]\x00){8,}", data):
        text = run16.group()[::2]
        urls |= set(m.group().decode("ascii", "replace") for m in URL_RE.finditer(text))
    return urls


def check_urls(platform, new, base, problems, facts):
    rel = MAIN_BINARY.get(platform, "Contents/MacOS/MultiMC")
    if rel not in new or rel not in base:
        problems.append("main binary %s not found" % rel)
        return
    nu, bu = embedded_urls(new[rel]), embedded_urls(base[rel])
    facts["embedded_urls"] = len(nu)
    for url in sorted(bu - nu):
        problems.append("URL in the baseline's main binary is missing: %s" % url)


def main(argv):
    out_json = None
    if "--json" in argv:
        i = argv.index("--json")
        out_json = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 3:
        print(__doc__)
        return 2
    platform, build_dir, baseline = argv
    problems, facts = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        base_root = extract_baseline(baseline, tmp)
        new, base = files(build_dir), files(base_root)
        for rel in sorted(set(new) - set(base)):
            problems.append("new file not in baseline: %s" % rel)
        for rel in sorted(set(base) - set(new)):
            problems.append("missing file that the baseline has: %s" % rel)
        if platform in ("lin64", "lin32"):
            check_linux(platform, new, base, problems, facts)
        elif platform == "win32":
            check_windows(new, base, problems, facts)
        elif platform.startswith("osx64"):
            check_macos(new, base, problems, facts)
        else:
            problems.append("unknown platform %s" % platform)
        check_urls(platform, new, base, problems, facts)
    facts["files"] = len(new)
    result = {"platform": platform, "baseline": os.path.basename(baseline),
              "passed": not problems, "problems": problems, "facts": facts}
    if out_json:
        with open(out_json, "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
    print("%s: %s (%d files)" % (platform, "PASS" if not problems else "FAIL", len(new)))
    for k, v in sorted(facts.items()):
        if k != "files":
            print("    %s: %s" % (k, v))
    for p in problems:
        print("  ! " + p)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
