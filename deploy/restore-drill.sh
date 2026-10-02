#!/bin/sh
# Retrieves one explicit encrypted snapshot, verifies it, and restores to a NEW quarantine DB.
set -eu
umask 077
: "${CLIENT_ID:?}" "${PYTHON:?}" "${APP_DIR:?}" "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD_FILE:?}"
: "${BACKUP_STAGING_ROOT:?}"
[ "$#" -eq 2 ] || { echo 'Usage: restore-drill.sh SNAPSHOT_HEX_ID NEW_DB_PATH' >&2; exit 2; }
case "$1" in ''|*[!0-9a-f]*) echo 'Explicit hexadecimal snapshot ID required' >&2; exit 2;; esac
[ ${#1} -ge 8 ] || { echo 'Snapshot ID must contain at least8characters' >&2; exit 2; }
[ "$(findmnt -n -o FSTYPE --target "$BACKUP_STAGING_ROOT")" = tmpfs ] || { echo 'Plaintext retrieval staging must be tmpfs' >&2; exit 2; }
[ ! -e "$2" ] && [ ! -L "$2" ] || { echo 'Restore target must not exist' >&2; exit 2; }
stage=$(mktemp -d "$BACKUP_STAGING_ROOT/restore.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
restic restore "$1" --target "$stage" >/dev/null
cd "$APP_DIR"
"$PYTHON" -m admin_agent.ops verify-backup --source "$stage/bundle" --client-id "$CLIENT_ID" >/dev/null
"$PYTHON" -m admin_agent.ops restore --source "$stage/bundle" --client-id "$CLIENT_ID" --target "$2"
