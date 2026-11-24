#!/bin/sh
# Scans added lines for secrets (staged by default, or a commit range). Exit 1 if any found.
pat='-----BEGIN [A-Z ]*PRIVATE KEY-----|\$apr1\$|\$2[aby]\$[0-9]{2}\$|(password|passwd|secret|token|api[_-]?key)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9/+_.-]{8,}|ghp_[A-Za-z0-9]{20,}|github_pat_|AKIA[0-9A-Z]{16}|(Set-)?Cookie:[[:space:]]*[^ ]+=|sshpass'
# default (pre-commit hook): staged additions.  --range <revs> (use before pushing): every line added by commits in the range, e.g.
#   scripts/secret-scan.sh --range origin/main..HEAD        or the whole history:  --range --all
if [ "${1:-}" = "--range" ]; then
  shift; [ $# -gt 0 ] || { echo "usage: secret-scan.sh --range <revs>|--all" >&2; exit 2; }
  src=$(git log -p -U0 --no-color --format= "$@" -- . ':!scripts/secret-scan.sh' ':!*.example.toml')
else
  src=$(git diff --cached -U0 --no-color -- . ':!scripts/secret-scan.sh' ':!*.example.toml')
fi
hits=$(printf '%s\n' "$src" | grep -E '^\+[^+]' | grep -Eiv 'secret-scan: allow' | grep -Ei -e "$pat")
if [ -n "$hits" ]; then
  echo "SECRET SCAN FAILED: possible secret staged (values not printed):" >&2
  echo "$(echo "$hits" | wc -l | tr -d ' ') suspicious added line(s); inspect with: git diff --cached (or git log -p <range>) | grep -Ei -e <pattern>" >&2
  echo "Remove it, or append 'secret-scan: allow' to a false-positive line." >&2
  exit 1
fi
