#!/bin/sh
# Restore config + DB from a backup tarball (root, on VM). Usage: restore.sh <tarball> [--target DIR]
# Default target is a scratch dir (safe dry restore for verification). Use --target / to restore in place (stop services first).
set -eu
TB=${1:?tarball}; TARGET=$(mktemp -d /tmp/tc-restore.XXXXXX)
[ "${2:-}" = "--target" ] && TARGET=${3:?dir}
mkdir -p "$TARGET/x"; tar -C "$TARGET/x" -xzf "$TB"
mkdir -p "$TARGET/etc" "$TARGET/var/lib/timecanvas"
tar -C "$TARGET" -xzf "$TARGET/x/b/etc-timecanvas.tgz"
cp "$TARGET/x/b/timecanvas.db" "$TARGET/var/lib/timecanvas/timecanvas.db"
[ "$(sqlite3 "$TARGET/var/lib/timecanvas/timecanvas.db" 'PRAGMA integrity_check;')" = "ok" ] || { echo "restored DB failed integrity check" >&2; exit 1; }
echo "restored into $TARGET (version: $(head -1 "$TARGET/x/b/VERSION")); media rows: $(sqlite3 "$TARGET/var/lib/timecanvas/timecanvas.db" 'select count(*) from media_files')"
