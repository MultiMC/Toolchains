# MultiMC Launcher toolchains and build automation

Everything needed to build and release the MultiMC Launcher (lin64, lin32, win32,
osx64-5.15.2) without the old build machines, while staying compatible with every system
it supports today (Windows XP, macOS 10.13, old glibc). Three parts:

| Directory | What | Changes |
|-----------|------|---------|
| [`snapshots/`](snapshots/README.md) | Raw captures of what was on the old machines: TeamCity's images and config, the shipped builds, the macmini, the Win7 build VM | Never modified. New capture = new dated directory. |
| [`containers/`](containers/README.md) | Sources for the toolchain images, one directory per image, plus the archive of built images | When a toolchain changes |
| [`automation/`](automation/README.md) | The build automation: build steps per platform, the runner, the release pipeline, the compatibility gate, settings | Everything else |

The flow: snapshots feed the container builds (base images, Qt, SDKs, the Windows
toolchain); the containers hold toolchains only; the automation mounts the source and its
build steps into them, builds, packages, and checks the result against the shipped builds
in the snapshots.

Large files (images, archives, VM disks, the Windows toolchain tree) are not in git. They
are on the main dev machine and mirrored to `mikoshi:~/mirror/MultiMC-Toolchains` by
`./mirror.sh` (exact copy, `--delete`; `--dry-run` shows what would change; it verifies
every `SHA256SUMS` on the mirror afterwards). Every directory with large files has a
`SHA256SUMS` and a README saying where they came from.
