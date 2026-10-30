# syntax=docker/dockerfile:1
# MultiMC deploy tools: repoman (hopper's files/deploy.py) and rclone (hopper's
# files/publish.py and website/publish.py), from primary sources only:
#
#   docker build -t multimc/toolchains/deployer:dev .
#
# The base is Debian 12, pinned by digest, the same as the translations and macos-osx64
# images. repoman needs nothing but python3.

FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
ENV LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive

# ca-certificates for rclone's TLS to the buckets
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 rclone ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# repoman2 without its S3 backend (local trees only; the buckets are rclone's), only the
# package itself, pinned by the full commit hash
ADD https://github.com/MultiMC/repoman2.git#4ce9a73b9a84b16fc35053415ad23eeb1bd7b10e:repoman \
    /usr/local/lib/python3.11/dist-packages/repoman

# What pip's console-script entry point (setup.py: repoman=repoman:main) would be
COPY --chmod=755 <<'EOF' /usr/local/bin/repoman
#!/usr/bin/python3
import sys
from repoman import main
sys.exit(main())
EOF

RUN repoman --help >/dev/null && rclone version
LABEL org.opencontainers.image.title="MultiMC deploy tools (repoman, rclone)"
