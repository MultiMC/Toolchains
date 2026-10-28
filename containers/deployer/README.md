# deployer: deploy tools

Image `multimc/toolchains/deployer:dev`: TeamCity's `deployer` image from the deth001
snapshot, plus rclone. Ubuntu 22.04 with `repoman` (repoman2, byte-identical to
github.com/MultiMC/repoman2 at c93931e, 2019), `s3cmd` 2.2.0 (no longer used), and
`patronupdater.py` from the snapshot; rclone 1.75.2 added (2026-10-24; checksum pinned in
the Dockerfile, taken from rclone's SHA256SUMS after checking its PGP signature).
hopper's `deploy.py` uses repoman exactly as TeamCity did, for parity (repoman is to
be reconsidered later); hopper's `publish.py` uses rclone for the buckets.

    zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-deployer.tar.zst | docker load
    docker build -t multimc/toolchains/deployer:dev .

Not archived separately: the snapshot image plus one pinned download, so it can be rebuilt.
