# site: the website's Hugo

Image `multimc/toolchains/site:dev`: Hugo, from primary sources only. hopper's
`website/build.py` builds multimc.org (the Website repo) with it.

    docker build -t multimc/toolchains/site:dev .

| Piece | From |
|-------|------|
| base | `debian:bookworm-slim` (12.15), pinned by digest, the same base as `deployer` and `translations` |
| `hugo` 0.169.0 (standard, not extended) | github.com/gohugoio/hugo releases, checksum pinned in the Dockerfile (from the release's `hugo_0.169.0_checksums.txt`) |

## History

Until 2026-11-16 the website was built with TeamCity's `site` image from the deth001
snapshot (`../../snapshots/2026-10-21-deth001`: Ubuntu 24.04, Hugo 0.31.1), published as
`ghcr.io/multimc/toolchains/site:2026-10-30` and tagged `site:latest` on the build server.
Hugo 0.31's Markdown (Blackfriday) dropped list items' paragraphs out of the list unless
they were indented by four spaces, which a news post ran into; the Website repo's templates
and config were ported to 0.169.0 then, and the output compared page by page.
