"""Persistent authentication for one isolated client; no public account provisioning."""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
import pyotp
from werkzeug.security import check_password_hash, generate_password_hash

from .errors import AppError
from .storage import encoded, now


ROLES = {"admin", "operator", "reader"}
SESSION_TTL = 8 * 3600
IDLE_TTL = 30 * 60
PREAUTH_TTL = 15 * 60
MAX_SESSIONS = 2000
PASSWORD_METHOD = "scrypt:32768:8:1"


def username_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", value):
        raise ValueError("Le nom utilisateur doit contenir 3 à 64 caractères minuscules, chiffres, point, tiret ou underscore.")
    return value


def password_value(value):
    if not isinstance(value, str) or not 14 <= len(value) <= 128 or not value.strip():
        raise ValueError("Le mot de passe doit contenir 14 à 128 caractères.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Mot de passe Unicode invalide.") from exc
    return value


class AuthStore:
    def __init__(self, store, client_id, client_name, secret):
        if not isinstance(secret, bytes) or not re.fullmatch(rb"[0-9a-fA-F]{64,128}", secret):
            raise ValueError("Secret session attendu : 64 à 128 caractères hexadécimaux aléatoires.")
        self.store = store
        self.client_id = client_id
        self.client_name = client_name
        self.secret = secret
        self.clock = time.time
        key = hmac.new(secret, b"admin-agent/mfa-encryption/v1", hashlib.sha256).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(key))
        # Match password work for nonexistent accounts. Never a usable account.
        self.dummy_password_hash = generate_password_hash(secrets.token_urlsafe(32), method=PASSWORD_METHOD)
        with store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("CREATE TABLE IF NOT EXISTS instance_identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), client_id TEXT NOT NULL, client_name TEXT NOT NULL, schema_version INTEGER NOT NULL)")
            identity = con.execute("SELECT * FROM instance_identity WHERE singleton=1").fetchone()
            if identity is not None:
                if identity["client_id"] != client_id or identity["schema_version"] != 1:
                    raise ValueError("La base appartient à une autre instance ou utilise une version incompatible.")
                con.execute("UPDATE instance_identity SET client_name=? WHERE singleton=1", (client_name,))
            else:
                business_tables = ("tasks", "documents", "finance_invoices", "finance_bank_transactions",
                                   "finance_allocations", "finance_bank_imports", "finance_events")
                existing_tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if any(con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                       for table in business_tables if table in existing_tables):
                    raise ValueError("Une base locale contenant des données métier ne peut pas être attribuée automatiquement à un client.")
                con.execute("INSERT INTO instance_identity VALUES (1,?,?,1)", (client_id, client_name))
            # Individual statements preserve the identity-binding transaction.
            for sql in (
                "CREATE TABLE IF NOT EXISTS auth_users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','operator','reader')), enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), totp_encrypted TEXT NOT NULL, last_totp_step INTEGER NOT NULL DEFAULT -1, created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, username TEXT REFERENCES auth_users(username), created_at REAL NOT NULL, expires_at REAL NOT NULL, last_seen REAL NOT NULL)",
                "CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(username)",
                "CREATE TABLE IF NOT EXISTS auth_rate_limits (bucket TEXT PRIMARY KEY, starts_at REAL NOT NULL, count INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS auth_events (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, details TEXT NOT NULL)",
            ):
                con.execute(sql)

    def _digest(self, purpose, value):
        return hmac.new(self.secret, (purpose + ":" + value).encode("utf-8"), hashlib.sha256).hexdigest()

    def _event(self, con, action, actor, details=None):
        # Security-log rolling retention: 90 days, at most 50,000 entries.
        # Dossier audit events use a separate non-pruned table.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
        con.execute("DELETE FROM auth_events WHERE created_at<?", (cutoff,))
        con.execute("DELETE FROM auth_events WHERE id <= (SELECT id FROM auth_events ORDER BY id DESC LIMIT 1 OFFSET 49999)")
        con.execute("INSERT INTO auth_events(action,actor,created_at,details) VALUES (?,?,?,?)", (action, actor, now(), encoded(details or {})))

    def record_event(self, action, actor, details=None):
        with self.store.connection() as con:
            self._event(con, action, actor, details)

    def _enrollment(self, username, secret, role):
        return {"username": username, "role": role, "totp_secret": secret,
                "provisioning_uri": pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="Admin Agent " + self.client_id)}

    def provision_user(self, username, password, role):
        username = username_value(username)
        password = password_value(password)
        if role not in ROLES:
            raise ValueError("Rôle invalide.")
        secret = pyotp.random_base32()
        password_hash = generate_password_hash(password, method=PASSWORD_METHOD)
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM auth_users WHERE username=?", (username,)).fetchone():
                raise ValueError("Cet utilisateur existe déjà.")
            con.execute("INSERT INTO auth_users(username,password_hash,role,totp_encrypted,created_at) VALUES (?,?,?,?,?)", (username, password_hash, role, self.fernet.encrypt(secret.encode()).decode(), now()))
            self._event(con, "user.created", "infrastructure_admin", {"username": username, "role": role})
        return self._enrollment(username, secret, role)

    def list_users(self):
        with self.store.connection() as con:
            return [dict(row, enabled=bool(row["enabled"]), mfa_required=True) for row in con.execute("SELECT username,role,enabled,created_at FROM auth_users ORDER BY username")]

    def _existing(self, con, username):
        username_value(username)
        row = con.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise ValueError("Utilisateur introuvable.")
        return row

    def _ensure_admin(self, con, row, role=None, enabled=None):
        removing = (role is not None and role != "admin") or enabled is False
        if removing and row["role"] == "admin" and row["enabled"] and con.execute("SELECT count(*) FROM auth_users WHERE role='admin' AND enabled=1").fetchone()[0] <= 1:
            raise ValueError("Impossible de retirer le dernier administrateur actif.")

    def set_user_enabled(self, username, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled doit être booléen.")
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._existing(con, username)
            self._ensure_admin(con, row, enabled=enabled)
            con.execute("UPDATE auth_users SET enabled=? WHERE username=?", (int(enabled), username))
            con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            self._event(con, "user.enabled" if enabled else "user.disabled", "infrastructure_admin", {"username": username})

    def set_user_role(self, username, role):
        if role not in ROLES:
            raise ValueError("Rôle invalide.")
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._existing(con, username)
            self._ensure_admin(con, row, role=role)
            con.execute("UPDATE auth_users SET role=? WHERE username=?", (role, username))
            con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            self._event(con, "user.role_changed", "infrastructure_admin", {"username": username, "role": role})

    def reset_password(self, username, password):
        password_hash = generate_password_hash(password_value(password), method=PASSWORD_METHOD)
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._existing(con, username)
            con.execute("UPDATE auth_users SET password_hash=? WHERE username=?", (password_hash, username))
            con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            self._event(con, "user.password_reset", "infrastructure_admin", {"username": username})

    def reset_mfa(self, username):
        secret = pyotp.random_base32()
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._existing(con, username)
            con.execute("UPDATE auth_users SET totp_encrypted=?,last_totp_step=-1 WHERE username=?", (self.fernet.encrypt(secret.encode()).decode(), username))
            con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            self._event(con, "user.mfa_reset", "infrastructure_admin", {"username": username})
        return self._enrollment(username, secret, row["role"])

    def revoke_user_sessions(self, username):
        with self.store.connection() as con:
            self._existing(con, username)
            con.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            self._event(con, "user.sessions_revoked", "infrastructure_admin", {"username": username})

    def revoke_all_sessions(self):
        with self.store.connection() as con:
            con.execute("DELETE FROM auth_sessions")
            self._event(con, "sessions.revoked", "infrastructure_admin")

    def rate_limit(self, purpose, value, limit, window=900):
        """Commit attempted work before returning an error, across restarts and workers."""
        timestamp = self.clock()
        bucket = self._digest("rate-" + purpose, value)
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM auth_rate_limits WHERE starts_at<?", (timestamp - 3600,))
            row = con.execute("SELECT * FROM auth_rate_limits WHERE bucket=?", (bucket,)).fetchone()
            if row is None or timestamp - row["starts_at"] >= window:
                con.execute("INSERT OR REPLACE INTO auth_rate_limits VALUES (?,?,1)", (bucket, timestamp))
                allowed = True
            else:
                allowed = row["count"] < limit
                con.execute("UPDATE auth_rate_limits SET count=count+1 WHERE bucket=?", (bucket,))
        if not allowed:
            raise AppError("Trop de tentatives. Réessayez dans 15 minutes.", 429, "rate_limited")

    def _cleanup(self, con):
        timestamp = self.clock()
        con.execute("DELETE FROM auth_sessions WHERE expires_at<=? OR last_seen<=?", (timestamp, timestamp - IDLE_TTL))

    def _new_session(self, con, username=None):
        self._cleanup(con)
        if con.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] >= MAX_SESSIONS:
            raise AppError("Sessions momentanément indisponibles.", 503, "session_capacity")
        token = secrets.token_urlsafe(32)
        timestamp = self.clock()
        con.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,?)", (self._digest("session", token), username, timestamp, timestamp + (SESSION_TTL if username else PREAUTH_TTL), timestamp))
        return token

    def new_anonymous_session(self, peer):
        self.rate_limit("session-mint", peer, 120)
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            return self._new_session(con)

    def get_session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        with self.store.connection() as con:
            row = con.execute("SELECT s.*,u.role,u.enabled FROM auth_sessions s LEFT JOIN auth_users u ON u.username=s.username WHERE token_hash=?", (self._digest("session", token),)).fetchone()
            timestamp = self.clock()
            if row is None:
                return None
            if row["expires_at"] <= timestamp or row["last_seen"] <= timestamp - IDLE_TTL or (row["username"] and not row["enabled"]):
                con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (row["token_hash"],))
                return None
            con.execute("UPDATE auth_sessions SET last_seen=? WHERE token_hash=?", (timestamp, row["token_hash"]))
            return dict(row)

    def csrf_token(self, token):
        return self._digest("csrf", token)

    def check_csrf(self, token, supplied):
        return isinstance(supplied, str) and bool(re.fullmatch(r"[0-9a-f]{64}", supplied)) and hmac.compare_digest(self.csrf_token(token), supplied)

    def authorize_mutation(self, con, token):
        """Recheck revocation within the same transaction as the dossier write."""
        row = con.execute("SELECT u.enabled,u.role,s.expires_at,s.last_seen FROM auth_sessions s JOIN auth_users u ON u.username=s.username WHERE s.token_hash=?", (self._digest("session", token),)).fetchone()
        timestamp = self.clock()
        if not row or not row["enabled"] or row["expires_at"] <= timestamp or row["last_seen"] <= timestamp - IDLE_TTL:
            raise AppError("Connexion requise.", 401, "auth_required")
        if row["role"] not in {"admin", "operator"}:
            raise AppError("Cette action n'est pas autorisée pour votre rôle.", 403, "forbidden")

    def login(self, token, username, password, otp, peer):
        # Peer bucket first: random usernames cannot trigger unlimited password hashes.
        self.rate_limit("login-peer", peer, 60)
        if not isinstance(username, str) or len(username) > 128:
            username = ""
        try:
            username.encode("utf-8")
        except UnicodeError:
            username = ""
        self.rate_limit("login-user", username.lower(), 5)
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            password = ""
        try:
            password.encode("utf-8")
            username.encode("utf-8")
        except UnicodeError:
            username, password = "", ""
        with self.store.connection() as con:
            row = con.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone()
        password_ok = check_password_hash(row["password_hash"] if row else self.dummy_password_hash, password)
        matched_step = None
        if row and password_ok and row["enabled"] and isinstance(otp, str) and re.fullmatch(r"[0-9]{6}", otp):
            try:
                totp = pyotp.TOTP(self.fernet.decrypt(row["totp_encrypted"].encode()).decode())
                step = int(self.clock()) // 30
                for candidate in (step - 1, step, step + 1):
                    if hmac.compare_digest(totp.at(candidate * 30), otp):
                        matched_step = candidate
                        break
            except (InvalidToken, ValueError, UnicodeError):
                matched_step = None
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            fresh = con.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone() if row else None
            active = con.execute("SELECT * FROM auth_sessions WHERE token_hash=?", (self._digest("session", token),)).fetchone()
            # Recheck account/secret/password inside write transaction to close races.
            valid = bool(fresh and fresh["enabled"] and matched_step is not None and matched_step > fresh["last_totp_step"]
                         and fresh["password_hash"] == row["password_hash"] and fresh["totp_encrypted"] == row["totp_encrypted"]
                         and active and active["expires_at"] > self.clock() and active["last_seen"] > self.clock() - IDLE_TTL)
            if valid:
                con.execute("UPDATE auth_users SET last_totp_step=? WHERE username=?", (matched_step, username))
                con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (self._digest("session", token),))
                new_token = self._new_session(con, username)
                self._event(con, "auth.login", username)
            else:
                # Account identifiers from unauthenticated input never enter logs.
                self._event(con, "auth.login_failed", "anonymous")
        if not valid:
            raise AppError("Identifiants ou code d’authentification invalides.", 401, "invalid_credentials")
        return new_token

    def logout(self, token, peer):
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT username FROM auth_sessions WHERE token_hash=?", (self._digest("session", token),)).fetchone()
            con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (self._digest("session", token),))
            self._event(con, "auth.logout", row["username"] if row and row["username"] else "anonymous")
        # Revocation commits BEFORE optional minting; capacity/rate failures must
        # never keep an authenticated session alive after an accepted logout.
        try:
            return self.new_anonymous_session(peer)
        except AppError as exc:
            if exc.code not in {"rate_limited", "session_capacity"}:
                raise
            return None
