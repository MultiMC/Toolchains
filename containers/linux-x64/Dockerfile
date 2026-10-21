# MultiMC lin64 toolchain: the TeamCity linux-x64 image as it was on deth001 (Ubuntu 14.04,
# g++-5, Qt 5.6.3 in /opt/qt56, cmake 3.10.0), imported unchanged. It can't be rebuilt from
# its original Dockerfile (Ubuntu ESM + PPAs), so the snapshot image is the source:
#
#   zstd -dc ../../snapshots/2026-10-21-deth001/images/toolchains-linux-x64.tar.zst | docker load
#   docker build -t multimc/toolchains/linux-x64:dev .
FROM ghcr.io/multimc/toolchains/linux-x64:latest
LABEL org.opencontainers.image.title="MultiMC lin64 toolchain"
