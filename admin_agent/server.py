"""Loopback-only HTTP API. No customer communication or execution endpoints."""

from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from .catalog import ROOT, get_skill, skill_body, skills
from .engine import analyze, result_status
from .errors import AppError
from .storage import Store


MAX_BODY = 65536
TASK_ROUTE = re.compile(r"^/api/tasks/([0-9a-f-]{36})(?:/(analyze|review|update))?$")


def mode():
    from .llm import ai_available
    return "ai_available" if ai_available() else "offline"


def analyze_task(store, task, use_ai=False):
    result = analyze(task)
    deterministic_status = result_status(result)
    if use_ai:
        from .llm import enrich_with_ai
        selected = get_skill(task["skill_id"])
        selected["body"], truncated = skill_body(selected)
        if truncated or not selected["body"]:
            raise AppError("Instructions de compétence absentes ou trop volumineuses pour l'analyse IA.", 409, "context_unavailable")
        resource_path = ROOT / "skills" / "_shared" / f"{task['country'].lower()}.md"
        country_reference = ""
        if resource_path.is_file():
            with resource_path.open("rb") as resource:
                country_bytes = resource.read(12001)
            if len(country_bytes) > 12000:
                raise AppError("Référence pays trop volumineuse pour l'analyse IA.", 409, "context_unavailable")
            country_reference = country_bytes.decode("utf-8")
        try:
            result = enrich_with_ai(task, result, selected, country_reference)
        except ValueError as exc:
            # Provider exceptions may contain secret header values. Use a fixed API error.
            raise AppError("Analyse IA indisponible ou réponse non vérifiable. Le contrôle local reste disponible. Vérifiez la configuration et le budget de contexte.", 409, "ai_unavailable") from exc
    return store.save_analysis(task["id"], result, task["version"], deterministic_status)


def demo_tasks():
    invoice = dict(invoice_number="DEMO-2026-014", supplier="Atelier Exemple", customer="Client Démonstration", issue_date="2026-07-01",
                   due_date="2026-07-31", net_amount="1000.00", vat_rate="20.00", vat_amount="200.00", total_amount="1200.00", currency="EUR", paid=False)
    return [
        dict(title="Relance à préparer · exemple fictif", description="Facture échue ; préparer uniquement un brouillon de suivi.",
             country="FR", skill_id="receivables-followup", payload=dict(invoice, disputed=False), idempotency_key="demo-v1-receivable"),
        dict(title="Écart de total · exemple fictif", description="Contrôler les montants avant tout traitement.", country="FR", skill_id="invoice-check",
             payload=dict(invoice, total_amount="1250.00"), idempotency_key="demo-v1-invoice"),
        dict(title="Pièces manquantes · exemple fictif", description="Préparer l'index mensuel pour le comptable.", country="ES", skill_id="bookkeeping-pack",
             payload={"period": "2026-07", "expected_documents": 3, "documents": [{"id": "demo-doc-1", "type": "purchase", "number": "F-001", "date": "2026-07-12", "total_amount": "121.00", "currency": "EUR"}]}, idempotency_key="demo-v1-bookkeeping"),
        dict(title="Trier une demande · exemple fictif", description="Une facture fournisseur et son justificatif sont à transmettre au comptable pour contrôle.",
             country="FR", skill_id="admin-triage", payload={}, idempotency_key="demo-v1-triage"),
    ]


class LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, store, web_root=None):
        if server_address[0] not in {"127.0.0.1", "localhost"}:
            raise ValueError("Le pilote ne peut écouter que sur 127.0.0.1 ou localhost.")
        self.store = store
        self.web_root = Path(web_root or ROOT / "web").resolve()
        super().__init__(("127.0.0.1", server_address[1]), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "AdminAgent/0.1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Do not put dossier titles, arbitrary request paths, provider errors or secrets in logs.
        pass

    def _headers(self, status, length, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _json(self, value, status=200, extra=None):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, len(body), extra=extra)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authority(self):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in allowed:
            raise AppError("Hôte non autorisé. Utilisez l'adresse locale du serveur.", 403, "host_forbidden")
        return hosts[0]

    def _mutation_allowed(self):
        host = self._authority()
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or origins and origins[0] != "http://" + host:
            raise AppError("Origine de requête refusée.", 403, "origin_forbidden")
        if self.headers.get("Sec-Fetch-Site", "") not in {"", "same-origin", "none"}:
            raise AppError("Requête provenant d'un autre site refusée.", 403, "origin_forbidden")
        if self.headers.get_content_type() != "application/json":
            raise AppError("Content-Type application/json obligatoire.", 415, "unsupported_media_type")

    def _body(self):
        if self.headers.get("Transfer-Encoding"):
            raise AppError("Transfer-Encoding n'est pas pris en charge.", 400, "invalid_transfer_encoding")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"\d{1,10}", lengths[0]):
            raise AppError("Content-Length valide obligatoire.", 411, "length_required")
        size = int(lengths[0])
        if size > MAX_BODY:
            raise AppError("Requête trop volumineuse.", 413, "payload_too_large")
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError()
            def reject_constant(value):
                raise ValueError()
            def unique_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            data = json.loads(raw.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_keys)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeDecodeError, RecursionError, TimeoutError) as exc:
            raise AppError("Le corps doit être un objet JSON valide avec des clés uniques.", 400, "invalid_json") from exc

    def _path(self):
        if len(self.path) > 2048:
            raise AppError("Chemin trop long.", 414, "uri_too_long")
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc:
            raise AppError("Chemin de requête invalide.")
        return parsed.path

    def _dispatch_get(self):
        self._authority()
        path = self._path()
        store = self.server.store
        if path == "/api/health":
            return self._json({"status": "ok", "mode": mode(), "outbound_enabled": False, "scope": "local_single_business_pilot"})
        if path == "/api/skills":
            return self._json({"skills": skills()})
        if path in {"/api/tasks", "/api/dashboard"}:
            tasks = store.list()
            if path == "/api/tasks":
                return self._json({"tasks": tasks})
            metrics = {"total": len(tasks), **{status: sum(task["status"] == status for task in tasks) for status in ("needs_review", "blocked", "ready")}}
            return self._json({"metrics": metrics, "tasks": tasks, "recent_events": store.events(limit=30), "mode": mode()})
        match = TASK_ROUTE.fullmatch(path)
        if match and match.group(2) is None:
            return self._json({"task": store.get(match.group(1)), "events": store.events(match.group(1))})
        if path == "/api/export":
            return self._json({"format_version": "1.0", "exported_on": date.today().isoformat(), "tasks": store.list(), "events": store.events(), "skills": skills(include_body=False)},
                              extra={"Content-Disposition": 'attachment; filename="admin-agent-export.json"'})
        if path.startswith("/api/"):
            raise AppError("Route introuvable.", 404, "not_found")
        decoded = unquote(path)
        if "\x00" in decoded or "\\" in decoded or any(part == ".." for part in decoded.split("/")):
            raise AppError("Chemin de fichier refusé.", 403, "path_forbidden")
        relative = "index.html" if decoded == "/" else decoded.lstrip("/")
        candidate = (self.server.web_root / relative).resolve()
        try:
            candidate.relative_to(self.server.web_root)
        except ValueError as exc:
            raise AppError("Chemin de fichier refusé.", 403, "path_forbidden") from exc
        if not candidate.is_file() or candidate.suffix.lower() not in {".html", ".js", ".css", ".svg", ".png", ".ico", ".woff2"}:
            raise AppError("Fichier introuvable.", 404, "not_found")
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if candidate.suffix.lower() in {".html", ".js", ".css", ".svg"}:
            content_type += "; charset=utf-8"
        self._headers(200, len(content), content_type)
        if self.command != "HEAD":
            self.wfile.write(content)

    def _dispatch_post(self):
        self._mutation_allowed()
        data = self._body()
        path = self._path()
        store = self.server.store
        if path == "/api/tasks":
            task, created = store.create(data)
            return self._json({"task": task}, 201 if created else 200)
        match = TASK_ROUTE.fullmatch(path)
        if match:
            task_id, action = match.groups()
            if action == "analyze":
                if set(data) - {"use_ai"} or type(data.get("use_ai", False)) is not bool:
                    raise AppError("use_ai doit être un booléen JSON et le seul champ.")
                return self._json({"task": analyze_task(store, store.get(task_id), data.get("use_ai", False))})
            if action == "review":
                if set(data) - {"decision", "note", "version"}:
                    raise AppError("Champs de relecture invalides.")
                return self._json({"task": store.review(task_id, data.get("decision"), data.get("note", ""), data.get("version"))})
            if action == "update":
                return self._json({"task": store.update(task_id, data)})
        if path == "/api/demo/seed":
            if data:
                raise AppError("Le chargement de démonstration attend un objet vide.")
            created = 0
            for row in demo_tasks():
                task, was_created = store.create(row)
                if was_created:
                    analyze_task(store, task)
                    created += 1
            return self._json({"created": created})
        raise AppError("Route introuvable. Aucune action externe n'est disponible.", 404, "not_found")

    def _handle(self, function):
        try:
            function()
        except AppError as exc:
            self._json({"error": {"code": exc.code, "message": exc.message}}, exc.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self._json({"error": {"code": "internal_error", "message": "Erreur interne. Aucune action externe n'a été exécutée."}}, 500)

    def do_GET(self):
        self._handle(self._dispatch_get)

    def do_HEAD(self):
        self._handle(self._dispatch_get)

    def do_POST(self):
        self._handle(self._dispatch_post)

    def _unsupported(self):
        self._json({"error": {"code": "method_not_allowed", "message": "Méthode non prise en charge."}}, 405, {"Allow": "GET, HEAD, POST"})

    do_OPTIONS = do_PUT = do_PATCH = do_DELETE = do_TRACE = do_CONNECT = _unsupported


def serve(port=8765, db_path=None, host="127.0.0.1"):
    store = Store(db_path or ROOT / ".data" / "admin-agent.sqlite3")
    server = LocalHTTPServer((host, port), store)
    print(f"Admin Agent local : http://127.0.0.1:{server.server_port} — aucun envoi externe", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
