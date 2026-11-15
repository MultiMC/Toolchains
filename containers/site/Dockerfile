# syntax=docker/dockerfile:1
# The website's Hugo (hopper's website/build.py), from primary sources only:
#
#   docker build -t multimc/toolchains/site:dev .
#
# The base is Debian 12, pinned by digest, the same as the deployer and translations images.
# Hugo is the standard (not extended) build: the site has no Sass or WebP to process.

FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
ENV LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive

# The checksum is the one in Hugo's hugo_0.169.0_checksums.txt for this release
# (github.com/gohugoio/hugo/releases/tag/v0.169.0)
ADD --checksum=sha256:2d2f0bfe357d8cb4cec02f6bb28a3bff34978c8dda44b618029c5eb9d66765a7 \
    https://github.com/gohugoio/hugo/releases/download/v0.169.0/hugo_0.169.0_linux-amd64.tar.gz /tmp/hugo.tar.gz
RUN tar -xzf /tmp/hugo.tar.gz -C /usr/local/bin hugo && rm /tmp/hugo.tar.gz

RUN hugo version
LABEL org.opencontainers.image.title="MultiMC website tools (Hugo)"
