# The Win7 build VM, 2026-10-21

The VM that built `win32` for TeamCity (libvirt domain `win7` on mikoshi), copied while shut
down. `SHA256SUMS` covers the large files (hashed from the originals).

| File | Contents |
|------|----------|
| `buildbot_w32.qcow2` | the disk, untouched (80 GB virtual, 34 GB used; no backing file, no snapshots) |
| `virtio-win-0.1.173.iso` | the driver ISO it mounts |
| `win7.libvirt.xml` | the VM definition (`virsh define win7.libvirt.xml` restores it) |
| `buildbot_w32.qemu-img-info.txt` | `qemu-img info` of the disk |
| `vm-CMake-3.20.1.tar.zst` | `C:\Program Files\CMake` extracted from the disk: the CMake the VM built with |
| `vm-msys32.tar.zst` | `C:\msys32` extracted from the disk (MSYS2; not used by the builds) |
| `compare/` | file-by-file hash comparison of the VM's toolchain against `containers/windows-win32/Tools` |

The comparison (`compare/report-*.txt`): Qt 5.6.3 + MinGW 4.9.2, Qt 5.15.2 + MinGW 8.1,
GnuWin32, JDK 8u112, OpenSSL and `dumpbin`/`link` are identical to the VM's (apart from
installer metadata). The CMake differs: the VM used 3.20.1, which is why
`containers/windows-win32/Tools/CMake-3.20.1` was taken from here.
