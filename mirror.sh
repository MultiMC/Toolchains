#!/bin/bash
# Mirror this directory, including the large files git doesn't have, to the backup copy,
# then verify every SHA256SUMS there.
#
# Usage: ./mirror.sh [--dry-run]
#
# The mirror is exact (rsync --delete): files removed or moved here are removed there too.
# Target: $MIRROR, default mikoshi.peterix.cz:mirror/MultiMC-Toolchains/

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MIRROR=${MIRROR:-mikoshi.peterix.cz:mirror/MultiMC-Toolchains/}
HOST=${MIRROR%%:*}
DIR=${MIRROR#*:}

if [ "${1:-}" = "--dry-run" ]; then
    rsync -aH --delete --dry-run --itemize-changes "$HERE/" "$MIRROR" \
        | grep -E '^(\*deleting|[<>c]f)' || true
    exit 0
fi

echo "syncing to $MIRROR"
rsync -aH --delete --delete-after --info=stats1 "$HERE/" "$MIRROR"

echo "verifying checksums on $HOST"
# shellcheck disable=SC2029
ssh "$HOST" "cd '$DIR' && failed=0
    for sums in \$(find . -name SHA256SUMS -not -path './.git/*' | sort); do
        if (cd \"\$(dirname \"\$sums\")\" && sha256sum --quiet -c SHA256SUMS); then
            echo \"  ok  \$(dirname \"\$sums\")\"
        else
            echo \"  BAD \$(dirname \"\$sums\")\"; failed=1
        fi
    done
    exit \$failed"
echo "mirror is up to date and verified"
