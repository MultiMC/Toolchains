# syntax=docker/dockerfile:1.20
FROM archlinux:base

LABEL org.opencontainers.image.title="MultiMC Windows Toolchain"
LABEL org.opencontainers.image.authors="Petr Mrázek, <peterix@gmail.com>"
ENV LANG=en_US.UTF-8

# Update all packages and install some things we may need
RUN yes | pacman -Syu && yes | pacman -Sy wine git curl && yes | pacman -Scc

RUN useradd -m -s /bin/bash builder

WORKDIR /home/builder
USER builder
SHELL ["/bin/bash", "-c"]

COPY --parents --chown=builder setup.sh Tools /home/builder/
RUN ls -al .
RUN ./setup.sh
