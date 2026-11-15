#!/bin/bash
# Publish a toolchain image on GitHub's container registry: the local
# multimc/toolchains/<name>:dev (build it first, see containers/<name>/README.md) goes out as
# ghcr.io/multimc/toolchains/<name>:<tag>, then the digest, the README row and the commands
# for the build server are printed.
#
# Usage: ./publish-image.sh <name> [tag]
#
# <name> is a directory in containers/ (not macos-osx64: it contains Apple's SDK, which can't
# be passed on). The tag defaults to today's date (UTC). Refuses when containers/<name> has
# uncommitted changes (what is published must be what git has) and when the tag is already
# published (published tags are never moved). Needs `docker login ghcr.io` with a token that
# may write packages.

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REGISTRY=ghcr.io/multimc/toolchains

die() { echo "error: $*" >&2; exit 1; }

[ $# -ge 1 ] && [ $# -le 2 ] || die "usage: $0 <name> [tag]"
name=$1
tag=${2:-$(date -u +%Y-%m-%d)}
local_image=multimc/toolchains/$name:dev
remote_image=$REGISTRY/$name:$tag

[ "$name" != macos-osx64 ] || die "macos-osx64 contains Apple's SDK and is never published"
[ -f "$HERE/containers/$name/Dockerfile" ] || die "no image $name (containers/$name/Dockerfile)"
dirty=$(git -C "$HERE" status --porcelain -- "containers/$name")
[ -z "$dirty" ] || die "containers/$name has uncommitted changes; commit them first:
$dirty"
docker image inspect "$local_image" >/dev/null 2>&1 || die "no local image $local_image; build it first"
if docker manifest inspect "$remote_image" >/dev/null 2>&1; then
    die "$remote_image is published already; published tags are never moved (give another tag)"
fi

commit=$(git -C "$HERE" log -1 --format='%h %cs' -- "containers/$name")
created=$(docker image inspect -f '{{.Created}}' "$local_image")
echo "publishing $local_image (created $created) as $remote_image"
echo "  containers/$name last changed in $commit"

docker tag "$local_image" "$remote_image"
push_log=$(mktemp)
trap 'rm -f "$push_log"' EXIT
docker push "$remote_image" | tee "$push_log"
digest=$(grep -o 'digest: sha256:[0-9a-f]\{64\}' "$push_log" | tail -1 | cut -d' ' -f2)
[ -n "$digest" ] || die "docker push printed no digest"
docker manifest inspect "$REGISTRY/$name@$digest" >/dev/null || die "$REGISTRY/$name@$digest isn't pullable"

id=$(docker image inspect -f '{{.Id}}' "$local_image")
if [ "$id" != "$digest" ]; then
    echo "note: the local image ID is $id; pull by the pushed digest above"
fi

cat <<EOF

Published $REGISTRY/$name:$tag, digest $digest.

The row for README.md, "Published images":

| \`$name\` | \`$tag\` | \`$local_image\` | \`$digest\` |

On the build server, as hopper:

    podman pull $REGISTRY/$name@$digest
    podman tag $REGISTRY/$name@$digest $local_image
EOF
