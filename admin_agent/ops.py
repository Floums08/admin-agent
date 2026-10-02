"""Offline operations for isolated client instances; never sends client communications."""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import sys
import tempfile


class OpsError(ValueError):
    """An expected operations refusal; messages contain no secret values."""


def _client_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", value):
        raise OpsError("Client ID must be 3-40 lowercase letters/digits/hyphens, starting with a letter.")
    return value


def _private_write(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def init_client(client_id, domain, directory, name=None):
    """Create a new private client directory, never modify an existing one."""
    _client_id(client_id)
    if not isinstance(domain, str) or len(domain) > 253 or not re.fullmatch(
        r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain
    ):
        raise OpsError("Provide a lowercase fully qualified DNS hostname, without scheme or path.")
    name = name or client_id
    if not isinstance(name, str) or not 1 <= len(name) <= 120 or any(c in name for c in "'\"$#\\\r\n") or any(ord(c) < 32 for c in name):
        raise OpsError("Client name contains unsupported configuration characters.")
    directory = Path(directory).absolute()
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(directory)):
        raise OpsError("Use a directory path without spaces or shell/interpolation characters.")
    if directory.exists() or directory.is_symlink():
        raise OpsError("Client directory already exists; refusing to overwrite configuration or secrets.")
    directory.mkdir(mode=0o700, parents=True)
    os.chmod(directory, 0o700)
    uid = os.getuid() if hasattr(os, "getuid") else 10001
    gid = os.getgid() if hasattr(os, "getgid") else 10001
    if uid == 0:
        uid = gid = 10001
    for child in ("data", "secrets", "evidence"):
        (directory / child).mkdir(mode=0o700)
    session_path = directory / "secrets/session_secret"
    restic_path = directory / "secrets/restic_password"
    _private_write(session_path, secrets.token_hex(32) + "\n")
    _private_write(restic_path, secrets.token_urlsafe(48) + "\n")
    # Compose local secrets are bind mounts: chmod/ownership on the host is authoritative.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.chown(directory / "data", uid, gid)
        os.chown(session_path, uid, gid)
    config = {"schema_version": 1, "client_id": client_id, "client_name": name,
              "domain": domain, "public_origin": "https://" + domain,
              "db": str(directory / "data/admin-agent.sqlite3"),
              "session_secret_file": str(session_path), "restic_password_file": str(restic_path),
              "uid": uid, "gid": gid}
    _private_write(directory / "client.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    lines = {"CLIENT_ID": client_id, "CLIENT_NAME": "'" + name + "'", "DOMAIN": domain,
             "CLIENT_DATA_DIR": str(directory / "data"), "SESSION_SECRET_PATH": str(session_path),
             "APP_UID": str(uid), "APP_GID": str(gid), "APP_IMAGE": "admin-agent:local"}
    _private_write(directory / "client.env", "".join(f"{key}={value}\n" for key, value in lines.items()))
    return {"created": True, "client_id": client_id, "config": str(directory / "client.json"),
            "compose_env": str(directory / "client.env"), "secrets_printed": False}


def load_config(path):
    path = Path(path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        _client_id(config["client_id"])
        for field in ("db", "session_secret_file", "restic_password_file"):
            if not Path(config[field]).is_absolute():
                raise OpsError("Configuration paths must be absolute.")
        if config.get("schema_version") != 1:
            raise OpsError("Unsupported client configuration version.")
        return config
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, OpsError):
            raise
        raise OpsError("Invalid or unreadable client configuration.") from exc


@contextmanager
def _readonly_db(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise OpsError("Database must be an existing regular file, not a symbolic link.")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        yield connection
    finally:
        connection.close()


def _identity(connection, expected_client):
    _client_id(expected_client)
    try:
        rows = connection.execute("SELECT client_id,client_name,schema_version FROM instance_identity").fetchall()
    except sqlite3.DatabaseError as exc:
        raise OpsError("Database has no supported bound client identity.") from exc
    if len(rows) != 1 or rows[0][0] != expected_client or rows[0][2] != 1:
        raise OpsError("Database identity/version differs from the expected client; operation refused.")
    return {"client_id": rows[0][0], "client_name": rows[0][1], "schema_version": rows[0][2]}


def _integrity(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise OpsError("SQLite integrity check failed.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise OpsError("SQLite foreign-key check failed.")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_database(db_path, client_id, destination):
    """SQLite online backup includes committed WAL state, unlike copying a live DB file."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise OpsError("Backup destination must not exist.")
    with _readonly_db(db_path) as source:
        _identity(source, client_id)
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        snapshot = destination / "database.sqlite3"
        try:
            descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                target.execute("PRAGMA journal_mode=DELETE")
                identity = _identity(target, client_id)
                _integrity(target)
            manifest = {"format": "admin-agent-sqlite-backup-v1", **identity,
                        "created_at": datetime.now(timezone.utc).isoformat(), "file": "database.sqlite3",
                        "size_bytes": snapshot.stat().st_size, "sha256": _sha256(snapshot),
                        "contains_secrets": "password hashes and session hashes; no plaintext secret files",
                        "encryption": "plaintext staging; restic required for off-host encrypted storage"}
            _private_write(destination / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        except Exception:
            shutil.rmtree(destination)
            raise
    return {"backup": str(destination), "client_id": client_id, "verified": True,
            "encrypted": False, "sha256": manifest["sha256"]}


def verify_backup(source, client_id):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise OpsError("Backup must be a directory, not a symbolic link.")
    manifest_path = source / "manifest.json"
    snapshot = source / "database.sqlite3"
    if manifest_path.is_symlink() or snapshot.is_symlink() or not snapshot.is_file():
        raise OpsError("Backup files must be regular files, not symbolic links.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OpsError("Unreadable backup manifest.") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "admin-agent-sqlite-backup-v1" or manifest.get("file") != "database.sqlite3":
        raise OpsError("Unsupported backup format.")
    if manifest.get("client_id") != _client_id(client_id):
        raise OpsError("Backup belongs to a different client.")
    if manifest.get("size_bytes") != snapshot.stat().st_size or manifest.get("sha256") != _sha256(snapshot):
        raise OpsError("Backup size/checksum mismatch.")
    try:
        with _readonly_db(snapshot) as connection:
            identity = _identity(connection, client_id)
            _integrity(connection)
    except sqlite3.DatabaseError as exc:
        raise OpsError("Backup is not an intact SQLite database.") from exc
    if identity["schema_version"] != manifest.get("schema_version"):
        raise OpsError("Backup schema metadata mismatch.")
    return manifest


def restore_database(source, client_id, target):
    """Restore to a NEW path only. An operator later swaps deployments, never this command."""
    manifest = verify_backup(source, client_id)
    target = Path(target)
    if target.exists() or target.is_symlink() or any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise OpsError("Restore target or SQLite sidecars already exist; refusing replacement.")
    if not target.parent.is_dir():
        raise OpsError("Create a protected target parent directory before restoring.")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output, (Path(source) / "database.sqlite3").open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush()
            os.fsync(output.fileno())
        if _sha256(target) != manifest["sha256"]:
            raise OpsError("Backup changed while restoring; operation refused.")
        with sqlite3.connect(target) as connection:
            _identity(connection, client_id)
            _integrity(connection)
            # Session table belongs to the production auth schema. Restores must require a new login.
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("auth_sessions", "auth_rate_limits"):
                if table in tables:
                    connection.execute(f"DELETE FROM {table}")
            # Old backups can resurrect disabled accounts or superseded passwords/MFA.
            # Every restored account therefore requires fresh credentials before re-enabling.
            if "auth_users" in tables:
                connection.execute("CREATE TABLE IF NOT EXISTS ops_recovery_pending (username TEXT PRIMARY KEY, password_reset INTEGER NOT NULL DEFAULT 0, mfa_reset INTEGER NOT NULL DEFAULT 0)")
                connection.execute("DELETE FROM ops_recovery_pending")
                connection.execute("INSERT INTO ops_recovery_pending(username) SELECT username FROM auth_users")
                connection.execute("UPDATE auth_users SET enabled=0,password_hash='!restore-reset-required',totp_encrypted='',last_totp_step=-1")
            connection.commit()
            connection.execute("PRAGMA journal_mode=DELETE")
            _integrity(connection)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"restored": str(target), "client_id": client_id, "sessions_revoked": True,
            "live_database_replaced": False, "restored_users_disabled": True,
            "required_next_steps": "Reset password and MFA for each retained user before user-enable."}


def _auth_store(config):
    from .storage import Store
    from .auth import AuthStore
    try:
        secret = Path(config["session_secret_file"]).read_bytes().strip()
    except OSError as exc:
        raise OpsError("Session secret file is unreadable.") from exc
    if not re.fullmatch(rb"[0-9a-fA-F]{64,128}", secret):
        raise OpsError("Session secret must contain 64-128 random hexadecimal characters.")
    auth = AuthStore(Store(config["db"]), config["client_id"], config["client_name"], secret)
    _secure_db(config)
    return auth


def _secure_db(config):
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(config["db"] + suffix)
        if path.exists():
            os.chmod(path, 0o600)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                os.chown(path, config["uid"], config["gid"])


def _recovery_status(db, username):
    with sqlite3.connect(db) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ops_recovery_pending'").fetchone()
        return connection.execute("SELECT password_reset,mfa_reset FROM ops_recovery_pending WHERE username=?", (username,)).fetchone() if exists else None


def manage_user(config_path, action, username, password=None, role="operator", enrollment_file=None):
    config = load_config(config_path)
    enrollment = action in {"user-add", "user-reset-mfa"}
    if enrollment:
        if enrollment_file:
            path = Path(enrollment_file)
            if path.exists() or path.is_symlink() or not path.parent.is_dir():
                raise OpsError("Enrollment output must be a new file in an existing protected directory.")
        elif not sys.stdout.isatty():
            raise OpsError("MFA enrollment requires a protected interactive terminal or --enrollment-file NEW_PATH.")
    auth = _auth_store(config)
    credentials = None
    if action == "user-add":
        credentials = auth.provision_user(username, password, role)
    elif action == "user-disable":
        auth.set_user_enabled(username, False)
    elif action == "user-enable":
        recovery = _recovery_status(config["db"], username)
        if recovery is not None and recovery != (1, 1):
            raise OpsError("Restored account requires password and MFA reset before re-enabling.")
        auth.set_user_enabled(username, True)
    elif action == "user-reset-password":
        auth.reset_password(username, password)
    elif action == "user-role":
        auth.set_user_role(username, role)
    elif action == "user-reset-mfa":
        credentials = auth.reset_mfa(username)
    else:
        raise OpsError("Unknown user operation.")
    if _recovery_status(config["db"], username) is not None:
        with sqlite3.connect(config["db"]) as connection:
            if action == "user-reset-password":
                connection.execute("UPDATE ops_recovery_pending SET password_reset=1 WHERE username=?", (username,))
            if action == "user-reset-mfa":
                connection.execute("UPDATE ops_recovery_pending SET mfa_reset=1 WHERE username=?", (username,))
    if credentials:
        secret_text = json.dumps(credentials, ensure_ascii=False, indent=2) + "\n"
        if enrollment_file:
            _private_write(enrollment_file, secret_text)
        else:
            print("MFA ENROLLMENT — register now in the named user's authenticator; do not record this in logs.")
            print(secret_text)
    _secure_db(config)
    return {"completed": True, "action": action, "username": username,
            "client_id": config["client_id"], "password_printed": False,
            "enrollment_file": str(enrollment_file) if enrollment_file else None}


def preflight(config_path, backup=None):
    """Read-only report. Manual attestations are never silently promoted to passed."""
    config = load_config(config_path)
    checks = []
    def check(code, passed, detail):
        checks.append({"id": code, "passed": bool(passed), "detail": detail})
    check("https_origin", config.get("public_origin") == "https://" + config.get("domain", "") and bool(config.get("domain")), "Exact HTTPS origin configured; DNS and live TLS still require external verification.")
    secret = Path(config["session_secret_file"])
    try:
        secret_ok = not secret.is_symlink() and secret.is_file() and bool(re.fullmatch(rb"[0-9a-fA-F]{64,128}", secret.read_bytes().strip()))
        permissions_ok = stat.S_IMODE(secret.stat().st_mode) & 0o077 == 0
    except OSError:
        secret_ok = permissions_ok = False
    check("session_secret", secret_ok, "Configured secret exists and meets the minimum length; value is not displayed.")
    check("secret_permissions", permissions_ok, "Session secret must have no group/other permissions.")
    database_path = Path(config["db"])
    try:
        private_db = not database_path.is_symlink() and stat.S_IMODE(database_path.stat().st_mode) & 0o077 == 0
    except OSError:
        private_db = False
    check("database_permissions", private_db, "Database must have no group/other permissions.")
    try:
        with _readonly_db(config["db"]) as connection:
            _identity(connection, config["client_id"])
            _integrity(connection)
        check("database", True, "SQLite integrity and client identity verified.")
    except (OpsError, sqlite3.DatabaseError):
        check("database", False, "Database missing, corrupt, unsupported or bound to a different client.")
    try:
        # This query is intentionally read-only: preflight must not initialize or migrate anything.
        with _readonly_db(config["db"]) as connection:
            admins = connection.execute("SELECT COUNT(*) FROM auth_users WHERE role='admin' AND enabled=1").fetchone()[0]
        check("named_admin", admins > 0, "At least one enabled named administrator is required.")
    except (OpsError, sqlite3.DatabaseError):
        check("named_admin", False, "No verifiable enabled administrator.")
    if backup:
        try:
            verify_backup(backup, config["client_id"])
            check("backup_integrity", True, "Supplied backup passes checksum/client identity/SQLite checks; this alone does not prove off-host encryption or recovery.")
        except (OpsError, OSError, sqlite3.DatabaseError):
            check("backup_integrity", False, "Supplied backup verification failed.")
    else:
        check("backup_integrity", False, "Supply --backup with a successfully restored and retrieved backup bundle.")
    manual = [{"id": code, "status": "pending", "required_evidence": text} for code, text in (
        ("client_scope_and_contract", "Signed scope, processor agreement, subprocessors, country, retention and responsible reviewers."),
        ("infrastructure_and_tls", "Deployed exact image, private app port, firewall, HTTPS certificate and encrypted host volume."),
        ("offsite_backup_and_restore", "Encrypted off-host snapshot, separately held recovery key, restoration drill, measured RPO/RTO."),
        ("access_and_monitoring", "Named-user least-privilege acceptance, support escalation, monitored health/disk/backup failures."),
        ("business_acceptance", "Synthetic then approved client cases reviewed; limitations accepted; browser visual verification."),
    )]
    return {"client_id": config["client_id"], "technical_ready": all(item["passed"] for item in checks),
            "launch_ready": False, "checks": checks, "manual_launch_checks": manual,
            "meaning": "Technical preflight never constitutes authorization or full production readiness."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Operations for one isolated Admin Agent client.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-client")
    init.add_argument("--client-id", required=True)
    init.add_argument("--domain", required=True)
    init.add_argument("--directory", required=True)
    init.add_argument("--name")
    for name in ("user-add", "user-disable", "user-enable", "user-reset-password", "user-role", "user-reset-mfa"):
        operation = sub.add_parser(name)
        operation.add_argument("--config", required=True)
        operation.add_argument("--username", required=True)
        if name in ("user-add", "user-role"):
            operation.add_argument("--role", choices=("admin", "operator", "reader"), default="operator")
        if name in ("user-add", "user-reset-password"):
            operation.add_argument("--password-stdin", action="store_true", help="Read one line from protected stdin; never pass a password as an argument.")
        if name in ("user-add", "user-reset-mfa"):
            operation.add_argument("--enrollment-file", help="Write MFA enrollment once to a NEW private file; never to logs.")
    flight = sub.add_parser("preflight")
    flight.add_argument("--config", required=True)
    flight.add_argument("--backup")
    back = sub.add_parser("backup")
    back.add_argument("--db", required=True)
    back.add_argument("--client-id", required=True)
    back.add_argument("--destination", required=True)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("--source", required=True)
    verify.add_argument("--client-id", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--source", required=True)
    restore.add_argument("--client-id", required=True)
    restore.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init-client":
            result = init_client(args.client_id, args.domain, args.directory, args.name)
        elif args.command.startswith("user-"):
            password = None
            if args.command in ("user-add", "user-reset-password"):
                if args.password_stdin:
                    password = sys.stdin.readline(2049).rstrip("\r\n")
                else:
                    password = getpass.getpass("New password (minimum 14 characters): ")
                    if password != getpass.getpass("Repeat password: "):
                        raise OpsError("Passwords do not match.")
            result = manage_user(args.config, args.command, args.username, password, getattr(args, "role", "operator"), getattr(args, "enrollment_file", None))
        elif args.command == "preflight":
            result = preflight(args.config, args.backup)
        elif args.command == "backup":
            result = backup_database(args.db, args.client_id, args.destination)
        elif args.command == "verify-backup":
            result = {"verified": True, "client_id": args.client_id, "manifest": verify_backup(args.source, args.client_id)}
        else:
            result = restore_database(args.source, args.client_id, args.target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if args.command != "preflight" or result["technical_ready"] else 2
    except (OpsError, OSError, sqlite3.DatabaseError) as exc:
        # OS/DB errors may contain deployment paths; do not print exception content.
        message = str(exc) if isinstance(exc, OpsError) else "Filesystem/database operation failed; inspect protected server diagnostics."
        print(json.dumps({"completed": False, "error": message}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"completed": False, "error": "Operation refused; check identity, role, password policy and configuration."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
