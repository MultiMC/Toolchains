# Containers

Sources for the toolchain images, one directory per image. Image name:
`multimc/toolchains/<directory>:dev`. Each directory has a `Dockerfile`, its inputs and a
README with how it was made and verified.

| Directory | Image for | Made from |
|-----------|-----------|-----------|
| [`linux-x64/`](linux-x64/README.md) | lin64 | the deth001 snapshot image, unchanged |
| [`linux-x32/`](linux-x32/README.md) | lin32 | the deth001 snapshot image + CMake 3.10.0 from source |
| [`windows-win32/`](windows-win32/README.md) | win32 | minimal Arch + GE-Proton10-15 + the Win7 VM's toolchain |
| [`macos-osx64/`](macos-osx64/README.md) | osx64-5.15.2 | Debian + osxcross + the macmini's SDK and Qt |
| [`translations/`](translations/README.md) | the translations repo's tooling | Debian + Qt 5.15.2 linguist tools |

## What the images contain

Toolchains only: no build steps, no entrypoint. The build steps are in
`../automation/build/`, and `../automation/run-build.sh` runs every platform the same way:

    docker run --rm --network none -u <uid>:<gid> \
        -v <source>:/src:ro -v <output>:/out -v automation/build:/build:ro <settings> \
        <image> bash /build/<platform script>

So a change to the build steps never needs an image rebuild; images change only when a
toolchain does.

## `archive/`

`docker save` of the built images, zstd-compressed (not in git; `SHA256SUMS` is). Load with
`zstd -dc <name>.tar.zst | docker load`. The fallback if an image can't be rebuilt (e.g.
osxcross fetches its own dependencies from GitHub during the build).

| File | Image |
|------|-------|
| `linux-x32.tar.zst` | `multimc/toolchains/linux-x32:dev` |
| `windows-win32.tar.zst` | `multimc/toolchains/windows-win32:dev` |
| `macos-osx64.tar.zst` | `multimc/toolchains/macos-osx64:dev` |
| `translations.tar.zst` | `multimc/toolchains/translations:dev` (also running on deth001) |
| `linux-x32-teamcity.tar.zst` | `ghcr.io/multimc/toolchains/linux-x32:cmake-3.10.0`, the hand-made fix TeamCity's Linux32 build uses on deth001 until the cutover |

`linux-x64` isn't archived separately: it is the snapshot image.
