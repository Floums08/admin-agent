#!/bin/sh
# Synthetic LOCAL repository test. This does not validate an off-host provider or live recovery SLA.
set -eu
umask 077
: "${PYTHON:=python3}"
: "${RESTIC_BINARY:=restic}"
command -v "$RESTIC_BINARY" >/dev/null
root=$(mktemp -d)
trap 'rm -rf -- "$root"' EXIT HUP INT TERM
export RESTIC_REPOSITORY="$root/encrypted-repository"
export RESTIC_PASSWORD_FILE="$root/restic-password"
export RESTIC_CACHE_DIR="$root/cache"
"$PYTHON" - "$root" <<'PY'
import pathlib, secrets, sys
from admin_agent.storage import Store
from admin_agent.auth import AuthStore
root=pathlib.Path(sys.argv[1])
(root/'restic-password').write_text(secrets.token_urlsafe(48))
(root/'restic-password').chmod(0o600)
store=Store(root/'source.sqlite3')
auth=AuthStore(store,'test-client','Synthetic QA client',secrets.token_hex(32).encode())
auth.provision_user('synthetic-admin','synthetic-test-password-only','admin')
store.create({'title':'RESTIC_SYNTHETIC_ONLY_MARKER','description':'Encrypted local roundtrip',
              'country':'FR','skill_id':'admin-triage','payload':{'text':'Document fictif'}})
PY
"$PYTHON" -m admin_agent.ops backup --db "$root/source.sqlite3" --client-id test-client --destination "$root/staging/bundle" >/dev/null
"$RESTIC_BINARY" init >/dev/null
(cd "$root/staging" && "$RESTIC_BINARY" backup --tag admin-agent:test-client --host test-client bundle >/dev/null)
"$RESTIC_BINARY" check --read-data >/dev/null
snapshot=$("$RESTIC_BINARY" snapshots --json | "$PYTHON" -c 'import json,sys; rows=json.load(sys.stdin); assert len(rows)==1; print(rows[0]["id"])')
"$RESTIC_BINARY" restore "$snapshot" --target "$root/retrieved" >/dev/null
"$PYTHON" -m admin_agent.ops verify-backup --source "$root/retrieved/bundle" --client-id test-client >/dev/null
"$PYTHON" -m admin_agent.ops restore --source "$root/retrieved/bundle" --client-id test-client --target "$root/quarantine.sqlite3" >/dev/null
"$PYTHON" - "$root" <<'PY'
import json, pathlib, sqlite3, sys
root=pathlib.Path(sys.argv[1])
a=json.loads((root/'staging/bundle/manifest.json').read_text())
b=json.loads((root/'retrieved/bundle/manifest.json').read_text())
assert a==b
with sqlite3.connect(root/'quarantine.sqlite3') as connection:
    assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==1
    assert connection.execute('SELECT count(*) FROM auth_sessions').fetchone()[0]==0
    assert connection.execute('SELECT count(*) FROM auth_users WHERE enabled=1').fetchone()[0]==0
    assert connection.execute('SELECT totp_encrypted FROM auth_users').fetchone()[0]==''
    assert connection.execute('SELECT password_hash FROM auth_users').fetchone()[0]=='!restore-reset-required'
# Direct plaintext task content must not appear in encrypted repository objects.
for file in (root/'encrypted-repository').rglob('*'):
    if file.is_file():
        assert b'RESTIC_SYNTHETIC_ONLY_MARKER' not in file.read_bytes()
print('PASS: real restic local encrypted backup/check/read-data/retrieve/verify/quarantine restore.')
print('Not tested: off-host repository, provider credentials, network recovery or client RPO/RTO.')
PY
