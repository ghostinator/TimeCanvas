#!/bin/sh
# Config + database backup (root, on VM). DB via SQLite online backup (consistent while in use). Keeps the last 14.
# Output: /var/backups/timecanvas/timecanvas-YYYYmmddTHHMMSS.tar.gz  (contains TLS key/htpasswd => dir is 0700 root)
# NOT included: the rolling frame archive and videos (media disk is excluded from Proxmox backups). Pinned videos list goes in pinned-videos.txt.
set -eu
D=/var/backups/timecanvas; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
install -d -m 0700 "$D"
mkdir "$T/b"
sqlite3 /var/lib/timecanvas/timecanvas.db ".backup '$T/b/timecanvas.db'"
[ "$(sqlite3 "$T/b/timecanvas.db" 'PRAGMA integrity_check;')" = "ok" ] || { echo "backup integrity check FAILED" >&2; exit 1; }
sqlite3 /var/lib/timecanvas/timecanvas.db "select m.path from media_files m join pinned_media p on p.media_id=m.id where m.media_type='video' and m.status='ok'" > "$T/b/pinned-videos.txt"
cp -a /opt/timecanvas/VERSION "$T/b/VERSION"
tar -C / -czf "$T/b/etc-timecanvas.tgz" etc/timecanvas
OUT="$D/timecanvas-$(date +%Y%m%dT%H%M%S).tar.gz"
tar -C "$T" -czf "$OUT" b
chmod 0600 "$OUT"
ls -1t "$D"/timecanvas-*.tar.gz | tail -n +15 | xargs -r rm -f
echo "$OUT"
