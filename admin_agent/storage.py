"""Single-business local SQLite store with atomic idempotency and audit records."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .catalog import MAX_PAYLOAD_BYTES, get_skill
from .engine import result_status
from .errors import AppError


audit_actor = ContextVar("audit_actor", default="local_operator")
audit_guard = ContextVar("audit_guard", default=None)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_task(data):
    if not isinstance(data, dict):
        raise AppError("Un objet JSON est attendu.")
    unknown = set(data) - {"title", "description", "skill_id", "country", "payload", "idempotency_key"}
    if unknown:
        raise AppError("Un ou plusieurs champs ne sont pas pris en charge.")
    clean = {}
    for field, max_length in (("title", 180), ("description", 12000), ("skill_id", 100), ("country", 2)):
        value = data.get(field, "")
        if not isinstance(value, str) or len(value) > max_length or (field != "description" and not value.strip()):
            raise AppError(f"Champ invalide : {field}.")
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise AppError(f"Texte Unicode invalide : {field}.") from exc
        clean[field] = value.strip()
    if clean["country"] not in {"FR", "ES"}:
        raise AppError("Le pays doit être FR ou ES.")
    get_skill(clean["skill_id"])
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise AppError("payload doit être un objet JSON.")
    stack, count = [(payload, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if depth > 16 or count > 5000:
            raise AppError("Le dossier contient trop de données imbriquées.", 413, "payload_too_large")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise AppError("Les noms de champs doivent être du texte.")
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    try:
        size = len(encoded(payload).encode("utf-8"))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AppError("Le dossier contient une valeur JSON invalide.") from exc
    if size > MAX_PAYLOAD_BYTES:
        raise AppError("Le dossier dépasse la limite de 32 000 octets.", 413, "payload_too_large")
    clean["payload"] = payload
    key = data.get("idempotency_key")
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", key)):
        raise AppError("Clé d'idempotence invalide (1 à 120 caractères alphanumériques, point, tiret, deux-points ou underscore).")
    return clean, key


class Store:
    def __init__(self, path, max_tasks=None, max_events=None, max_result_bytes=None):
        self.max_tasks = max_tasks
        self.max_events = max_events
        self.max_result_bytes = max_result_bytes
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE, request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    action TEXT NOT NULL, created_at TEXT NOT NULL, details TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_task_id ON events(task_id, id);
            """)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _event(self, connection, task_id, action, details):
        guard = audit_guard.get()
        if guard is not None:
            guard(connection)
        if self.max_events is not None and connection.execute("SELECT count(*) FROM events").fetchone()[0] >= self.max_events:
            raise AppError("Capacité de journal atteinte. Contactez l’administrateur avant de poursuivre.", 409, "capacity_reached")
        details = dict(details, actor=audit_actor.get())
        connection.execute("INSERT INTO events(task_id,action,created_at,details) VALUES (?,?,?,?)",
                           (task_id, action, now(), encoded(details)))

    @staticmethod
    def _get(connection, task_id):
        row = connection.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise AppError("Dossier introuvable.", 404, "not_found")
        return json.loads(row["body"])

    def create(self, data):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._create(connection, data)

    def create_imported(self, data):
        """Trusted server-side connector entrypoint; never exposed by an HTTP route."""
        clean, key = validate_task(data)
        source = clean["payload"].get("_connector_source")
        if not isinstance(source, dict):
            raise AppError("La provenance du connecteur est obligatoire.")
        imported = {key: value for key, value in clean["payload"].items() if key != "_connector_source"}
        clean["payload"] = dict(imported, _connector_source=dict(source, imported_values=imported, changed_since_import=[]))
        clean["idempotency_key"] = key
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._create(connection, clean, allow_connector_source=True)

    def _create(self, connection, data, allow_document_source=False, allow_connector_source=False):
        """Create inside an existing transaction, including document linkage."""
        clean, key = validate_task(data)
        if "_document_source" in clean["payload"] and not allow_document_source:
            raise AppError("La provenance documentaire doit être créée par l'import contrôlé.")
        if "_connector_source" in clean["payload"] and not allow_connector_source:
            raise AppError("La provenance du connecteur doit être créée par l'import contrôlé.")
        request_hash = hashlib.sha256(encoded(clean).encode()).hexdigest()
        if key:
            previous = connection.execute("SELECT body,request_hash FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise AppError("Cette clé d'idempotence est déjà associée à un dossier différent.", 409, "idempotency_conflict")
                return json.loads(previous["body"]), False
        if self.max_tasks is not None and connection.execute("SELECT count(*) FROM tasks").fetchone()[0] >= self.max_tasks:
            raise AppError("Capacité de dossiers atteinte. Contactez l’administrateur.", 409, "capacity_reached")
        timestamp = now()
        task = dict(id=str(uuid.uuid4()), **clean, status="new", created_at=timestamp, updated_at=timestamp, result=None, version=1)
        connection.execute("INSERT INTO tasks(id,body,idempotency_key,request_hash,created_at) VALUES (?,?,?,?,?)",
                           (task["id"], encoded(task), key, request_hash, timestamp))
        self._event(connection, task["id"], "task.created", {"skill_id": task["skill_id"], "country": task["country"], "actor": "local_operator"})
        return task, True

    def get(self, task_id):
        with self.connection() as connection:
            return self._get(connection, task_id)

    def list(self, summaries=False):
        with self.connection() as connection:
            result = []
            for row in connection.execute("SELECT body FROM tasks ORDER BY created_at DESC, rowid DESC"):
                task = json.loads(row["body"])
                if summaries:
                    task.pop("payload", None)
                    task.pop("result", None)
                    task["summary_only"] = True
                result.append(task)
            return result

    def events(self, task_id=None, limit=None):
        query = "SELECT id,task_id,action,created_at,details FROM events"
        parameters = []
        if task_id:
            query += " WHERE task_id=?"
            parameters.append(task_id)
        query += " ORDER BY id DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.connection() as connection:
            return [dict(row, details=json.loads(row["details"])) for row in connection.execute(query, parameters)]

    def save_analysis(self, task_id, result, expected_version, status=None):
        if self.max_result_bytes is not None and len(encoded(result).encode("utf-8")) > self.max_result_bytes:
            raise AppError("Résultat trop volumineux. Répartissez les pièces en plusieurs petits dossiers avant de relancer l'analyse.", 413, "result_too_large")
        status = status or result_status(result)
        if status not in {"blocked", "needs_review"}:
            raise AppError("Statut d'analyse invalide.")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._get(connection, task_id)
            if task["version"] != expected_version:
                raise AppError("Le dossier a changé pendant l'analyse. Rechargez-le.", 409, "version_conflict")
            task.update(result=result, status=status, updated_at=now(), version=task["version"] + 1)
            connection.execute("UPDATE tasks SET body=? WHERE id=?", (encoded(task), task_id))
            self._event(connection, task_id, "task.analyzed", {"status": status, "mode": result["mode"], "outbound_executed": False,
                                                              "version": task["version"], "actor": "local_operator"})
            return task

    def update(self, task_id, data):
        if not isinstance(data, dict) or set(data) - {"title", "description", "payload", "version"}:
            raise AppError("Champs de modification invalides.")
        if type(data.get("version")) is not int or data["version"] < 1:
            raise AppError("La version actuelle du dossier est obligatoire.")
        if not set(data) & {"title", "description", "payload"}:
            raise AppError("Aucune modification fournie.")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._get(connection, task_id)
            if data["version"] != task["version"]:
                raise AppError("Le dossier a changé. Rechargez-le avant de modifier.", 409, "version_conflict")
            candidate = {key: task[key] for key in ("title", "description", "skill_id", "country", "payload")}
            candidate.update({key: value for key, value in data.items() if key != "version"})
            existing_source = task["payload"].get("_document_source")
            if isinstance(candidate.get("payload"), dict):
                submitted_source = candidate["payload"].get("_document_source")
                if submitted_source is not None and submitted_source != existing_source:
                    raise AppError("La provenance documentaire ne peut pas être modifiée.")
                if existing_source:
                    source = dict(existing_source)
                    source["changed_since_document_review"] = sorted(key for key in (set(source["fields"]) | (set(candidate["payload"]) - {"_document_source"}))
                        if key not in source["fields"] or key not in candidate["payload"] or candidate["payload"].get(key) != source["fields"][key]["reviewed_value"])
                    candidate["payload"] = dict(candidate["payload"], _document_source=source)
                existing_connector = task["payload"].get("_connector_source")
                submitted_connector = candidate["payload"].get("_connector_source")
                if submitted_connector is not None and submitted_connector != existing_connector:
                    raise AppError("La provenance du connecteur ne peut pas être modifiée.")
                if existing_connector:
                    source = dict(existing_connector)
                    imported = source["imported_values"]
                    source["changed_since_import"] = sorted(key for key in (set(imported) | (set(candidate["payload"]) - {"_connector_source"}))
                        if key not in imported or key not in candidate["payload"] or candidate["payload"].get(key) != imported[key])
                    candidate["payload"] = dict(candidate["payload"], _connector_source=source)
            clean, _ = validate_task(candidate)
            task.update(**clean, status="new", result=None, updated_at=now(), version=task["version"] + 1)
            connection.execute("UPDATE tasks SET body=? WHERE id=?", (encoded(task), task_id))
            self._event(connection, task_id, "task.updated", {"fields": sorted(set(data) - {"version"}), "previous_review_invalidated": True,
                                                             "version": task["version"], "actor": "local_operator"})
            return task

    def review(self, task_id, decision, note, expected_version=None):
        if type(expected_version) is not int or expected_version < 1:
            raise AppError("La version du dossier relu est obligatoire.")
        if not isinstance(decision, str) or decision not in {"approve", "reject"}:
            raise AppError("La décision doit être approve ou reject.")
        if not isinstance(note, str) or len(note) > 2000:
            raise AppError("La note de relecture doit être un texte de 2 000 caractères maximum.")
        try:
            note.encode("utf-8")
        except UnicodeError as exc:
            raise AppError("La note contient un texte Unicode invalide.") from exc
        if decision == "reject" and len(note.strip()) < 3:
            raise AppError("Précisez le motif du rejet (3 caractères minimum).")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._get(connection, task_id)
            if task["version"] != expected_version:
                raise AppError("Le dossier a changé depuis votre relecture. Rechargez-le avant de décider.", 409, "version_conflict")
            if not task["result"]:
                raise AppError("Analysez le dossier avant de le relire.", 409, "analysis_required")
            if decision == "approve" and (task["status"] not in {"needs_review", "ready"} or result_status(task["result"]) == "blocked"):
                raise AppError("Ce dossier comporte des blocages ou doit être réanalysé avant validation.", 409, "approval_blocked")
            if decision == "approve" and task["result"].get("analyzed_on") != datetime.now().date().isoformat():
                raise AppError("Les contrôles de dates doivent être actualisés. Relancez l'analyse avant validation.", 409, "analysis_stale")
            if decision == "approve" and task["skill_id"] == "expense-review":
                from .engine import expense_duplicates
                others = [json.loads(row["body"]) for row in connection.execute("SELECT body FROM tasks")]
                if expense_duplicates(task, others):
                    raise AppError("Un doublon potentiel de note de frais est présent. Relancez l'analyse et rapprochez les justificatifs.", 409, "expense_duplicate_detected")
            task.update(status="ready" if decision == "approve" else "rejected", updated_at=now(), version=task["version"] + 1)
            connection.execute("UPDATE tasks SET body=? WHERE id=?", (encoded(task), task_id))
            self._event(connection, task_id, "task.reviewed", {"decision": decision, "note": note.strip(), "actor": "local_operator",
                                                              "outbound_executed": False, "meaning": "internal_output_review_only", "version": task["version"]})
            return task
