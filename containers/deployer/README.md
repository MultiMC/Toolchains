# deployer: deploy tools

Image `multimc/toolchains/deployer:dev`: TeamCity's `deployer` image from the deth001
snapshot, unchanged. Ubuntu 22.04 with `repoman` (repoman2, byte-identical to
github.com/MultiMC/repoman2 at c93931e, 2019), `s3cmd` 2.2.0, `patronupdater.py`.
Used by `../../automation/deploy.py` exactly as TeamCity used it, for parity; to be
reconsidered later (repoman, the slowness of `s3cmd sync`).

    zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-deployer.tar.zst | docker load
    docker build -t multimc/toolchains/deployer:dev .

Not archived separately: it is the snapshot image.
