# dumpbin: our own `dumpbin /dependents`

The win32 build bundles its DLLs with CMake's `fixup_bundle`, which finds each binary's
dependencies with `CMAKE_GP_TOOL=dumpbin` (hopper's `launcher/steps/win32.sh`). The old VM
had Microsoft's `dumpbin.exe`/`link.exe`/`mspdb80.dll` (VS 2008) in `Tools/Tools` for this,
which can't be redistributed. `dumpbin.c` replaces them, so the image can be published.

It does only `dumpbin /dependents FILE...`: the imported DLLs, then the delay-loaded ones,
laid out like Microsoft's (same headings, four-space indent, CRLF), without the banner and
section summary that CMake doesn't read. Any other option is refused. The image builds it
with its own MinGW 4.9.2 (`Dockerfile`) into `Tools/Tools/dumpbin.exe`, where the build
already looks for it.

Why not MinGW's `objdump`: CMake's `GetPrerequisites` can use it, but `objdump -p` prints
the whole export table too, and CMake parsing that line by line for every Qt DLL makes the
install step very slow. `dumpbin /dependents` output is a few lines.

## Verification (2026-10-30)

Compared with Microsoft's dumpbin (9.00.30729.01, from the VM), both run under the image's
Wine, on the lines `GetPrerequisites` matches (`^    <name>.dll$`) plus the headings:

- the 26 binaries of the shipped `mmc-develop-win32.zip`: 21 identical. On the other 5
  (`libeay32`, `ssleay32`, `libgcc_s_dw2-1`, `libssp-0`, `libstdc++-6`) Microsoft's dumpbin
  stops with `LNK1000: Internal error during DumpSections` (exit 5) and lists nothing; ours
  lists their imports, which match binutils' `objdump -p` exactly. Their dependencies are
  system DLLs or already in the bundle, so the bundle doesn't change (below).
- 152 MSVC-built binaries from `Tools/` (CMake 3.20.1, the JDK, link.exe itself), 21 of
  them with delay-load imports: all identical.
- a file that isn't a PE image: Microsoft's prints a warning and exits 0; ours prints an
  error to stderr and exits 1. `GetPrerequisites` ignores the exit status either way.

Speed under Wine: 152 runs took 2.7 s vs 6.2 s with Microsoft's (mostly Wine process start).

Full clean win32 builds of develop da162756 with the image before and after the change
(`multimc/toolchains/windows-win32:dev` vs this one): the same 30 files; `MultiMC.exe` and
every DLL byte-identical; the jars have identical contents and the `.dll.a` differs only in
archive timestamps, as between any two builds; both pass the compatibility gate and all 15
tests. Install step 4 s vs 5 s, whole build 73 s vs 76 s.
