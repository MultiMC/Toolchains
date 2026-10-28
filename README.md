# MultiMC Launcher toolchains

The toolchains needed to build the MultiMC Launcher (lin64, lin32, win32,
osx64-5.15.2) without the old build machines, while staying compatible with every system
it supports today (Windows XP, macOS 10.13, old glibc), and the images of the tools the other release jobs run. Two parts:

| Directory | What | Changes |
|-----------|------|---------|
| [`snapshots/`](snapshots/README.md) | Raw captures of what was on the old machines: TeamCity's images and config, the shipped builds, the macmini, the Win7 build VM | Never modified. New capture = new dated directory. |
| [`containers/`](containers/README.md) | Sources for the toolchain and tool images, one directory per image, plus the archive of built images | When a toolchain or tool changes |

The flow: snapshots feed the container builds (base images, Qt, SDKs, the Windows
toolchain); the containers hold toolchains only. The build automation, [hopper](https://github.com/MultiMC/hopper),
is its own repo: it mounts the source and its build steps into the images, builds, packages,
and checks the result against the compatibility baselines taken from the shipped builds in
the snapshots.

Large files (images, archives, VM disks, the Windows toolchain tree) are not in git. They
are on the main dev machine and mirrored to `mikoshi:~/mirror/MultiMC-Toolchains` by
`./mirror.sh` (exact copy, `--delete`; `--dry-run` shows what would change; it verifies
every `SHA256SUMS` on the mirror afterwards). Every directory with large files has a
`SHA256SUMS` and a README saying where they came from.
