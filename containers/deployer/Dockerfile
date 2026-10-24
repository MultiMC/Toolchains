# MultiMC deploy tools: TeamCity's deployer image as it was on deth001 (Ubuntu 22.04,
# repoman2 at c93931e, s3cmd 2.2.0, the Patreon credits script), plus rclone.
#
#   zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-deployer.tar.zst | docker load
#   docker build -t multimc/toolchains/deployer:dev .
FROM ghcr.io/multimc/toolchains/deployer:latest
LABEL org.opencontainers.image.title="MultiMC deploy tools"

# rclone, for uploading to the R2 buckets (parallel, unlike s3cmd). The checksum is the one
# in rclone's SHA256SUMS for this release, whose PGP signature (Nick Craig-Wood, key
# FBF737ECE9F8AB18604BD2AC93935E02FF3B54FA) was verified on 2026-10-24.
ADD --checksum=sha256:349ac8fba6ff65d6247043f1750cdcb518ec5d500ef91463a10d37c0ccdf3702 \
    https://downloads.rclone.org/v1.75.2/rclone-v1.75.2-linux-amd64.zip /tmp/rclone.zip
RUN unzip -q -j /tmp/rclone.zip "rclone-v1.75.2-linux-amd64/rclone" -d /usr/local/bin \
    && chmod 755 /usr/local/bin/rclone \
    && rm /tmp/rclone.zip
