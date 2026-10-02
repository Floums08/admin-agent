#!/bin/sh
# Called with protected environment supplied by systemd, never source an untrusted file.
set -eu
umask 077
: "${CLIENT_ID:?}" "${CLIENT_CONFIG:?}" "${CLIENT_DB:?}" "${PYTHON:?}" "${APP_DIR:?}"
: "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD_FILE:?}" "${RESTIC_CACHE_DIR:?}"
: "${BACKUP_STAGING_ROOT:?}" "${BACKUP_STATUS_FILE:?}"
command -v restic >/dev/null
command -v findmnt >/dev/null
command -v flock >/dev/null
[ -f "$RESTIC_PASSWORD_FILE" ] || { echo 'Missing restic password file' >&2; exit 2; }
[ "$(stat -c '%a' "$RESTIC_PASSWORD_FILE")" = 600 ] || { echo 'Restic password must be mode600' >&2; exit 2; }
[ "$(findmnt -n -o FSTYPE --target "$BACKUP_STAGING_ROOT")" = tmpfs ] || { echo 'Plaintext staging must be tmpfs' >&2; exit 2; }
case "$RESTIC_REPOSITORY" in s3:*|sftp:*|rest:https://*|b2:*|azure:*|gs:*|rclone:*) ;; *) echo 'Require an explicitly configured off-host repository' >&2; exit 2;; esac
# Fail closed if not initialized/reachable; never silently create a repository with the wrong key.
restic cat config >/dev/null
exec 9>"$BACKUP_STAGING_ROOT/backup.lock"
flock -n 9 || { echo 'A backup is already running' >&2; exit 2; }
stage=$(mktemp -d "$BACKUP_STAGING_ROOT/run.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
cd "$APP_DIR"
"$PYTHON" -m admin_agent.ops backup --db "$CLIENT_DB" --client-id "$CLIENT_ID" --destination "$stage/bundle" >/dev/null
"$PYTHON" -m admin_agent.ops verify-backup --source "$stage/bundle" --client-id "$CLIENT_ID" >/dev/null
# Relative path makes restore independent of a changing staging directory.
(cd "$stage" && restic backup --tag "admin-agent:$CLIENT_ID" --host "$CLIENT_ID" bundle >/dev/null)
restic check >/dev/null
"$PYTHON" - "$BACKUP_STATUS_FILE" "$CLIENT_ID" <<'PY'
from datetime import datetime, timezone
import json, os, pathlib, sys, tempfile
path = pathlib.Path(sys.argv[1])
fd, temporary = tempfile.mkstemp(prefix='.backup-status-', dir=path.parent)
with os.fdopen(fd, 'w') as stream:
    json.dump({'client_id': sys.argv[2], 'last_success': datetime.now(timezone.utc).isoformat(),
               'encrypted_offhost_snapshot': True, 'repository_check': True,
               'restore_drill_verified': False}, stream)
os.replace(temporary, path)
PY
printf '%s\n' 'Encrypted backup and repository check completed; no restore drill implied.'
