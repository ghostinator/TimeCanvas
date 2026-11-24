#!/bin/sh
# Deploy a committed ref (default HEAD) from the Mac to the VM. Never deploys uncommitted work.
# Usage: scripts/deploy.sh [ref]     env: TC_HOST=user@vm-address (required)
set -eu
cd "$(git rev-parse --show-toplevel)"
REF=${1:-HEAD}; HOST=${TC_HOST:?set TC_HOST=user@vm-address (the VM you deploy to)}
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean; commit first" >&2; exit 1; }
COMMIT=$(git rev-parse --short=12 "$REF^{commit}"); VER=$(git describe --tags --always "$REF")
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
git archive "$REF" | tar -x -C "$STAGE"
printf '%s\ncommit %s\n' "$VER" "$COMMIT" > "$STAGE/VERSION"
rsync -a --delete -e ssh "$STAGE/" "$HOST:/tmp/tc-stage/"
ssh "$HOST" 'sudo sh /tmp/tc-stage/scripts/install.sh'
echo "deployed $VER ($COMMIT) to $HOST"
