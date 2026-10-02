"""Operator-only read-only connector preview and explicit local import.

Run on the trusted Linux host as its operator (root is supported, as in ops.py).
No network source is reachable through an HTTP API of Admin Agent.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from .connectors import ConnectorError, MEDIA_TYPES, _digest, _json, _regular_bytes, scan, validate_config
from .errors import AppError
from .ops import OpsError, _identity, _readonly_db, _secure_db, load_config
from .storage import Store, audit_actor, audit_guard


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ConnectorError("Duplicate JSON configuration keys are refused.")
        value[key] = item
    return value


def load_connectors(path, client_id):
    try:
        document = json.loads(_regular_bytes(path, 64000), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ConnectorError):
            raise
        raise ConnectorError("Invalid connector configuration JSON.") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "client_id", "connectors"} or document["schema_version"] != 1 or document["client_id"] != client_id:
        raise ConnectorError("Connector configuration belongs to another client or uses an unsupported schema.")
    configs = document["connectors"]
    if not isinstance(configs, list) or not 1 <= len(configs) <= 20:
        raise ConnectorError("Configure between 1 and 20 connectors.")
    ids = set()
    for config in configs:
        validate_config(config)
        if config["id"] in ids:
            raise ConnectorError("Connector ids must be unique and stable.")
        ids.add(config["id"])
    return {config["id"]: config for config in configs}


def _previous_invoice(store, key, source_hash, mapped_hash):
    with store.connection() as connection:
        row = connection.execute("SELECT body FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
    if not row:
        return None
    task = json.loads(row["body"])
    provenance = task.get("payload", {}).get("_connector_source", {})
    if provenance.get("sha256") != source_hash or provenance.get("mapped_sha256") != mapped_hash:
        raise ConnectorError("Source changed since its first import; review and reconcile the existing dossier manually. No replacement occurred.")
    return task


def import_invoice(store, item, country):
    stable_key = "connector:" + hashlib.sha256((item.connector_id + "\x00" + item.source_key).encode()).hexdigest()
    mapped_hash = _digest(_json({"country": country, "payload": item.payload}))
    previous = _previous_invoice(store, stable_key, item.sha256, mapped_hash)
    if previous:
        return previous, False
    payload = dict(item.payload)
    payload["_connector_source"] = {"connector_id": item.connector_id, "source_key": item.source_key,
                                    "sha256": item.sha256, "mapped_sha256": mapped_hash, "fetched_at": item.fetched_at,
                                    "review_required": True, "source_is_live_balance": False}
    task = {"title": "Facture importée — " + payload.get("invoice_number", "à compléter")[:150],
            "description": "Import en lecture seule. Vérifier les champs sur la source et confirmer l'état actuel avant utilisation.\n" + "\n".join(item.warnings),
            "skill_id": "invoice-check", "country": country, "payload": payload, "idempotency_key": stable_key}
    try:
        return store.create_imported(task)
    except AppError as exc:
        # Same source scanned concurrently can differ only by fetched_at. Return the
        # committed original without rewriting its evidence or review state.
        if exc.code == "idempotency_conflict":
            previous = _previous_invoice(store, stable_key, item.sha256, mapped_hash)
            if previous:
                return previous, False
        raise


def run(client_config, connector_config, connector_id, apply=False, page=0):
    client = load_config(client_config)
    if any(type(client.get(field)) is not int or client[field] < 0 for field in ("uid", "gid")):
        raise ConnectorError("Client configuration must include valid application uid/gid from init-client.")
    database = Path(client["db"])
    if any(path.is_symlink() for path in (database, *database.parents)) or any(Path(str(database) + suffix).is_symlink() for suffix in ("-wal", "-shm", "-journal")):
        raise ConnectorError("Database and sidecar paths must not contain symbolic links.")
    if hasattr(os, "geteuid") and os.geteuid() not in {0, client["uid"]}:
        raise ConnectorError("Run as root or the configured application uid; do not create database files under an unrelated owner.")
    # Read-only verification happens BEFORE credentials are loaded or sources queried.
    # Never instantiate AuthStore here: that could relabel an empty/demo database.
    with _readonly_db(client["db"]) as connection:
        _identity(connection, client["client_id"])
    try:
        return _run_verified(client, connector_config, connector_id, apply, page)
    finally:
        # A root-operated SQLite connection can create root-owned WAL/SHM files,
        # including read-only access. Restore the app's configured UID like ops.py.
        _secure_db(client)


def _run_verified(client, connector_config, connector_id, apply, page):
    configs = load_connectors(connector_config, client["client_id"])
    if connector_id not in configs:
        raise ConnectorError("Connector id is absent from the client configuration.")
    config = configs[connector_id]
    items = scan(config, page=page)
    result = {"client_id": client["client_id"], "connector_id": connector_id, "kind": config["kind"],
              "mode": "import" if apply else "preview", "remote_writes": False,
              "count": len(items), "items": [item.preview() for item in items],
              "pagination": {"page": page, "page_size": 20, "next_page_possible": len(items) == 20} if config["kind"] == "dolibarr" else None}
    if not apply:
        return result
    store = Store(client["db"], max_tasks=100, max_events=20000, max_result_bytes=32768)
    actor_token = audit_actor.set("connector_cli:" + connector_id)
    guard_token = audit_guard.set(lambda connection: _identity(connection, client["client_id"]))
    try:
        document_store = None
        outcomes = []
        for item in items:
            try:
                if item.kind == "document":
                    if document_store is None:
                        from .documents import DocumentStore
                        document_store = DocumentStore(store)
                    record, created = document_store.add(item.content, item.filename,
                                                         declared_media_type=MEDIA_TYPES[Path(item.filename).suffix.lower()],
                                                         source={"connector_id": item.connector_id, "source_key": item.source_key, "fetched_at": item.fetched_at})
                else:
                    record, created = import_invoice(store, item, config["country"])
                outcomes.append({"source_key": item.source_key, "kind": item.kind, "id": record["id"], "created": created, "status": "imported" if created else "already_imported"})
            except (AppError, ConnectorError) as exc:
                outcomes.append({"source_key": item.source_key, "kind": item.kind, "status": "refused",
                                 "error": str(exc) if isinstance(exc, ConnectorError) else exc.code})
        result["outcomes"] = outcomes
        result["completed"] = not any(outcome["status"] == "refused" for outcome in outcomes)
        result["batch_atomic"] = False
        result["local_changes_only"] = True
        return result
    finally:
        audit_guard.reset(guard_token)
        audit_actor.reset(actor_token)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview read-only source snapshots; --import explicitly creates local unreviewed records. Never sends mail or modifies a source.")
    parser.add_argument("--client-config", required=True, help="Absolute path to this client's ops client.json")
    parser.add_argument("--connector-config", required=True, help="Absolute path to connectors.json (credentials live in separate mode-0600 files)")
    parser.add_argument("--connector", required=True, help="Stable connector id from configuration")
    parser.add_argument("--page", type=int, default=0, help="Dolibarr page, zero-based; each page contains at most 20 records")
    parser.add_argument("--import", dest="apply", action="store_true", help="Import the inspected source batch locally; partial success is reported per item")
    args = parser.parse_args(argv)
    try:
        result = run(args.client_config, args.connector_config, args.connector, args.apply, args.page)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result.get("completed", True) else 2
    except (ConnectorError, OpsError, AppError, OSError, ValueError, sqlite3.DatabaseError) as exc:
        message = str(exc) if isinstance(exc, (ConnectorError, OpsError)) else "Operation refused; check source format, permissions and client configuration."
        print(json.dumps({"completed": False, "remote_writes": False, "error": message}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
