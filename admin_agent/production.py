"""TLS-terminated, authenticated WSGI service: one database and instance per client."""

from dataclasses import dataclass, field
from datetime import date
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, request, send_from_directory, stream_with_context
from werkzeug.exceptions import HTTPException

from .auth import AuthStore, SESSION_TTL
from .catalog import ROOT, skills
from .errors import AppError
from .server import MAX_BODY, analyze_task
from .storage import Store, audit_actor, audit_guard, encoded


COOKIE_NAME = "__Host-admin_agent_session"
MAX_TASKS = 100
MAX_EVENTS = 20000
MAX_RESULT_BYTES = 32768
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


@dataclass(frozen=True)
class ProductionConfig:
    client_id: str
    client_name: str
    public_origin: str
    db_path: Path
    secret: bytes = field(repr=False)
    bind: str = "127.0.0.1"
    port: int = 8765

    def validate(self):
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", self.client_id):
            raise ValueError("ADMIN_AGENT_CLIENT_ID doit contenir 3 à 40 caractères minuscules/chiffres/tirets et commencer par une lettre.")
        if not isinstance(self.client_name, str) or not 1 <= len(self.client_name.strip()) <= 120 or any(ord(c) < 32 for c in self.client_name):
            raise ValueError("ADMIN_AGENT_CLIENT_NAME invalide.")
        parsed = urlsplit(self.public_origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("ADMIN_AGENT_PUBLIC_ORIGIN doit être une origine HTTPS complète sans chemin final.")
        if self.public_origin != "https://" + parsed.netloc or parsed.netloc.lower() != parsed.netloc or any(c.isspace() for c in parsed.netloc):
            raise ValueError("ADMIN_AGENT_PUBLIC_ORIGIN non canonique.")
        try:
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("Port HTTPS public invalide.") from exc
        if not Path(self.db_path).is_absolute() or str(self.db_path) == ":memory:":
            raise ValueError("ADMIN_AGENT_DB doit être un chemin absolu persistant.")
        if not isinstance(self.secret, bytes) or not re.fullmatch(rb"[0-9a-fA-F]{64,128}", self.secret):
            raise ValueError("Le fichier secret doit contenir 64 à 128 caractères hexadécimaux aléatoires.")
        if self.bind not in {"127.0.0.1", "0.0.0.0"} or type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Adresse ou port interne invalide.")
        if os.environ.get("ADMIN_AGENT_AI_ENABLED", "0") != "0":
            raise ValueError("L'IA doit rester désactivée dans cette version de production.")
        return self

    @classmethod
    def from_environment(cls):
        required = ("ADMIN_AGENT_CLIENT_ID", "ADMIN_AGENT_CLIENT_NAME", "ADMIN_AGENT_PUBLIC_ORIGIN", "ADMIN_AGENT_DB", "ADMIN_AGENT_SESSION_SECRET_FILE")
        if any(not os.environ.get(key) for key in required):
            raise ValueError("Configuration production incomplète : identité, origine HTTPS, base et fichier secret obligatoires.")
        secret_path = Path(os.environ["ADMIN_AGENT_SESSION_SECRET_FILE"])
        if not secret_path.is_absolute() or not secret_path.is_file() or secret_path.stat().st_size > 130:
            raise ValueError("Fichier secret absent ou invalide.")
        secret = secret_path.read_bytes().strip()
        return cls(client_id=os.environ["ADMIN_AGENT_CLIENT_ID"], client_name=os.environ["ADMIN_AGENT_CLIENT_NAME"],
                   public_origin=os.environ["ADMIN_AGENT_PUBLIC_ORIGIN"], db_path=Path(os.environ["ADMIN_AGENT_DB"]), secret=secret,
                   bind=os.environ.get("ADMIN_AGENT_BIND", "127.0.0.1"), port=int(os.environ.get("ADMIN_AGENT_PORT", "8765"))).validate()


def create_app(config=None):
    config = (config or ProductionConfig.from_environment()).validate()
    store = Store(config.db_path, max_tasks=MAX_TASKS, max_events=MAX_EVENTS, max_result_bytes=MAX_RESULT_BYTES)
    auth = AuthStore(store, config.client_id, config.client_name, config.secret)
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=MAX_BODY, PROPAGATE_EXCEPTIONS=False)
    app.extensions.update(store=store, auth=auth, production_config=config)
    public_host = urlsplit(config.public_origin).netloc

    def response_error(message, status, code):
        return jsonify(error={"code": code, "message": message}), status

    def set_cookie(response, token):
        if not token:
            response.delete_cookie(COOKIE_NAME, secure=True, httponly=True, samesite="Strict", path="/")
            return response
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, secure=True, httponly=True, samesite="Strict", path="/")
        return response

    def session_payload(token, session):
        role = session.get("role") if session else None
        user = {"username": session["username"], "role": role} if session and session.get("username") else None
        return {"authenticated": bool(user), "user": user, "csrf_token": auth.csrf_token(token) if token else None,
                "expires_at": int(session["expires_at"]) if session else None, "idle_timeout_seconds": 1800 if user else 900,
                "client": {"id": config.client_id, "name": config.client_name}, "scope": "production_single_client", "mode": "offline",
                "capabilities": {**{key: role in {"admin", "operator"} for key in ("create", "analyze", "update", "review")}, "export": role == "admin", "demo": False}}

    def body():
        if request.mimetype != "application/json":
            raise AppError("Content-Type application/json obligatoire.", 415, "unsupported_media_type")
        if request.content_length is None:
            raise AppError("Content-Length obligatoire.", 411, "length_required")
        if request.content_length > MAX_BODY:
            raise AppError("Requête trop volumineuse.", 413, "payload_too_large")
        def reject_constant(value):
            raise ValueError()
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        try:
            data = json.loads(request.get_data(cache=False).decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_pairs)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise AppError("Le corps doit être un objet JSON valide avec des clés uniques.", 400, "invalid_json") from exc

    def require_role(*roles):
        if not g.session or not g.session.get("username"):
            raise AppError("Connexion requise.", 401, "auth_required")
        if g.session.get("role") not in roles:
            raise AppError("Cette action n'est pas autorisée pour votre rôle.", 403, "forbidden")

    @app.before_request
    def protections():
        # Reverse-proxy headers are intentionally ignored. The internal port must
        # remain private; Waitress sets the fixed HTTPS scheme for the TLS terminator.
        if request.host != public_host:
            raise AppError("Hôte non autorisé.", 403, "host_forbidden")
        if len(request.full_path) > 2048:
            raise AppError("Chemin trop long.", 414, "uri_too_long")
        if request.path not in {"/healthz", "/readyz"} and request.scheme != "https":
            raise AppError("HTTPS est obligatoire.", 403, "https_required")
        if request.method not in {"GET", "HEAD", "POST"}:
            raise AppError("Méthode non prise en charge.", 405, "method_not_allowed")
        g.token = request.cookies.get(COOKIE_NAME, "")
        g.session = auth.get_session(g.token)
        g.audit_token = audit_actor.set(g.session["username"] if g.session and g.session.get("username") else "anonymous")
        token_for_guard = g.token
        g.guard_token = audit_guard.set(lambda con: auth.authorize_mutation(con, token_for_guard))
        if request.method == "POST":
            if request.headers.get("Origin") != config.public_origin or request.headers.get("Sec-Fetch-Site", "same-origin") not in {"same-origin", "none"}:
                raise AppError("Origine de requête refusée.", 403, "origin_forbidden")
            if not g.session or not auth.check_csrf(g.token, request.headers.get("X-CSRF-Token")):
                raise AppError("Session ou jeton de sécurité expiré. Rechargez la page.", 403, "csrf_invalid")
        if request.path.startswith("/api/") and request.path not in {"/api/session", "/api/login", "/api/logout"}:
            require_role("admin", "operator", "reader")
            auth.rate_limit("api-user", g.session["username"], 300)

    @app.teardown_request
    def reset_actor(_error):
        if hasattr(g, "audit_token"):
            audit_actor.reset(g.pop("audit_token"))
        if hasattr(g, "guard_token"):
            audit_guard.reset(g.pop("guard_token"))

    @app.after_request
    def security_headers(response):
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                                 "X-Frame-Options": "DENY", "Content-Security-Policy": CSP,
                                 "Strict-Transport-Security": "max-age=31536000", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
        if response.status_code == 429:
            response.headers["Retry-After"] = "900"
        return response

    @app.errorhandler(AppError)
    def expected_error(exc):
        return response_error(exc.message, exc.status, exc.code)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return response_error("Requête refusée.", exc.code, "request_rejected")

    @app.errorhandler(Exception)
    def internal_error(_exc):
        # No arbitrary exception strings, SQL values, request paths or secrets.
        app.logger.error("admin_agent_request_failed")
        return response_error("Erreur interne. Aucune action externe n'a été exécutée.", 500, "internal_error")

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz():
        try:
            with store.connection() as con:
                row = con.execute("SELECT client_id,schema_version FROM instance_identity WHERE singleton=1").fetchone()
                if not row or row["client_id"] != config.client_id or row["schema_version"] != 1:
                    raise sqlite3.DatabaseError()
                con.execute("SELECT id FROM tasks LIMIT 1").fetchall()
            return jsonify(status="ok")
        except (sqlite3.Error, OSError):
            return jsonify(status="unavailable"), 503

    @app.get("/api/session")
    def session_info():
        token = g.token
        if not g.session:
            token = auth.new_anonymous_session(request.remote_addr or "unknown")
        return set_cookie(jsonify(session_payload(token, auth.get_session(token))), token)

    @app.post("/api/login")
    def login():
        data = body()
        if set(data) != {"username", "password", "otp"}:
            raise AppError("Identifiant, mot de passe et code d’authentification requis.")
        token = auth.login(g.token, data["username"], data["password"], data["otp"], request.remote_addr or "unknown")
        return set_cookie(jsonify(session_payload(token, auth.get_session(token))), token)

    @app.post("/api/logout")
    def logout():
        if body():
            raise AppError("La déconnexion attend un objet vide.")
        token = auth.logout(g.token, request.remote_addr or "unknown")
        return set_cookie(jsonify(session_payload(token, auth.get_session(token))), token)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", mode="offline", outbound_enabled=False, scope="production_single_client")

    @app.get("/api/skills")
    def skills_route():
        return jsonify(skills=skills())

    @app.get("/api/tasks")
    def list_tasks():
        return jsonify(tasks=store.list(summaries=True))

    @app.get("/api/dashboard")
    def dashboard():
        tasks = store.list(summaries=True)
        return jsonify(metrics={"total": len(tasks), **{status: sum(task["status"] == status for task in tasks) for status in ("needs_review", "blocked", "ready")}},
                       tasks=tasks, recent_events=store.events(limit=30), mode="offline")

    @app.get("/api/tasks/<uuid:task_id>")
    def get_task(task_id):
        with store.connection() as con:
            total = con.execute("SELECT count(*) FROM events WHERE task_id=?", (str(task_id),)).fetchone()[0]
        return jsonify(task=store.get(str(task_id)), events=store.events(str(task_id), limit=200), events_total=total, events_truncated=total > 200)

    @app.post("/api/tasks")
    def create_task():
        require_role("admin", "operator")
        task, created = store.create(body())
        return jsonify(task=task), 201 if created else 200

    @app.post("/api/tasks/<uuid:task_id>/update")
    def update_task(task_id):
        require_role("admin", "operator")
        return jsonify(task=store.update(str(task_id), body()))

    @app.post("/api/tasks/<uuid:task_id>/analyze")
    def analyze_route(task_id):
        require_role("admin", "operator")
        data = body()
        if set(data) - {"use_ai"} or type(data.get("use_ai", False)) is not bool:
            raise AppError("use_ai doit être un booléen et le seul champ.")
        if data.get("use_ai"):
            raise AppError("L'analyse IA externe est désactivée dans cette version de production.", 403, "ai_disabled")
        return jsonify(task=analyze_task(store, store.get(str(task_id)), False))

    @app.post("/api/tasks/<uuid:task_id>/review")
    def review_task(task_id):
        require_role("admin", "operator")
        data = body()
        if set(data) - {"decision", "note", "version"}:
            raise AppError("Champs de relecture invalides.")
        return jsonify(task=store.review(str(task_id), data.get("decision"), data.get("note", ""), data.get("version")))

    @app.get("/api/export")
    def export():
        require_role("admin")
        if request.method == "HEAD":
            raise AppError("Utilisez GET pour télécharger l'export.", 405, "method_not_allowed")
        auth.rate_limit("export-user", g.session["username"], 5)
        auth.record_event("data.exported", g.session["username"])
        def stream():
            prefix = {"format_version": "1.0", "exported_on": date.today().isoformat(), "client": {"id": config.client_id, "name": config.client_name}, "skills": skills(include_body=False)}
            yield encoded(prefix)[:-1] + ',"tasks":['
            with store.connection() as con:
                # One read transaction gives the export a consistent snapshot.
                con.execute("BEGIN")
                first = True
                for row in con.execute("SELECT body FROM tasks ORDER BY created_at,id"):
                    yield ("" if first else ",") + row["body"]
                    first = False
                yield '],"events":['
                first = True
                for row in con.execute("SELECT id,task_id,action,created_at,details FROM events ORDER BY id"):
                    yield ("" if first else ",") + encoded(dict(row, details=json.loads(row["details"])))
                    first = False
            yield "]}"
        response = Response(stream_with_context(stream()), content_type="application/json; charset=utf-8")
        response.headers["Content-Disposition"] = 'attachment; filename="admin-agent-export.json"'
        return response

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "web", "index.html")

    @app.get("/<path:asset>")
    def static_asset(asset):
        # A fixed public shell only; no source, backups, data, uploads or hidden files.
        if asset not in {"app.js", "styles.css", "favicon.ico"}:
            raise AppError("Fichier introuvable.", 404, "not_found")
        return send_from_directory(ROOT / "web", asset)

    return app


def main():
    from waitress import serve
    config = ProductionConfig.from_environment()
    os.umask(0o077)
    app = create_app(config)
    serve(app, host=config.bind, port=config.port, threads=4, channel_timeout=30, max_request_body_size=MAX_BODY,
          max_request_header_size=16384, connection_limit=100, clear_untrusted_proxy_headers=True, url_scheme="https",
          expose_tracebacks=False, ident="AdminAgent")


if __name__ == "__main__":
    main()
