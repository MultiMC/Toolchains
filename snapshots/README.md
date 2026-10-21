# Snapshots

Raw captures of what was on the old build machines, kept as they were captured. Nothing in
here is edited after the fact (the one exception: secrets removed from the TeamCity copy).
A new capture goes into a new dated directory.

| Directory | Captured from | Used by |
|-----------|---------------|---------|
| [`2026-10-21-deth001/`](2026-10-21-deth001/README.md) | deth001.multimc.org: TeamCity's toolchain images, the shipped downloads | `containers/linux-*` (base images), `automation` (compatibility baselines) |
| [`2026-10-21-teamcity/`](2026-10-21-teamcity/README.md) | TeamCity's project configuration on deth001 | reference: how the old builds ran |
| [`2026-10-21-macmini/`](2026-10-21-macmini/README.md) | macmini.peterix.cz: Qt, CMake.app, Xcode SDKs | `containers/macos-osx64` |
| [`2026-10-21-win7-vm/`](2026-10-21-win7-vm/README.md) | The Win7 build VM disk on mikoshi | reference for `containers/windows-win32` (its toolchain was verified against it) |
