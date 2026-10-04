"""Bounded original documents, isolated OCR and reviewed, immutable provenance.

Binary formats are never parsed in the application process. Originals, revisions
and task linkage share the client SQLite database and its atomic backup boundary.
"""

import hashlib
import json
import math
import re
import time
import unicodedata
import uuid
from urllib import error, request

from .errors import AppError
from .storage import audit_actor, audit_guard, encoded, now, validate_task


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
MAX_DOCUMENTS = 100
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_EXTRACTION_BYTES = 1024 * 1024
MAX_EXTRACTION_TOTAL = 20 * 1024 * 1024
MAX_REVISIONS = 5
LANGUAGES = {"eng", "fra", "spa", "fra+spa+eng"}
MEDIA_TYPES = {"application/pdf", "image/png", "image/jpeg"}
CANDIDATE_FIELDS = {"invoice_number", "supplier", "customer", "issue_date", "due_date", "net_amount", "vat_amount", "vat_rate", "total_amount", "currency", "merchant", "expense_date"}
REVIEW_FIELDS = CANDIDATE_FIELDS | {"paid", "disputed", "paid_amount", "remaining_amount", "text", "bank_details_changed"}
EXPENSE_FIELDS = {"merchant", "expense_date", "total_amount", "currency", "vat_amount", "employee_ref", "business_purpose", "category", "payment_method", "paid_by_company", "reimbursed", "business_only", "policy_ref", "policy_confirmed", "policy_limit", "policy_currency", "payment_confirmed"}
METADATA_COLUMNS = "id,filename,media_type,size_bytes,sha256,created_at,created_by,status,extraction_version,task_id,last_error,language"
DOCUMENT_RISKS = {
    "partial_payment": r"\b(?:acompte|paiement partiel|reglement partiel|partial payment|partially paid|advance payment|down payment|payment on account|pago parcial|pagado parcialmente|pago a cuenta|anticipo)\b",
    "credit_note": r"\b(?:avoir|credit note|factura rectificativa|nota de credito)\b",
    "special_vat": r"\b(?:autoliquidation|reverse charge|inversion del sujeto pasivo|autoliquidacion)\b",
    "bank_change": r"\b(?:nouveau rib|changement de rib|changement iban|nouvel iban|bank details changed|new bank account|new iban|nuevo iban|cambio de cuenta)\b",
    "retention": r"\b(?:retenue de garantie|withholding|retencion|garantia retenida)\b",
}


def _text(value, maximum):
    return isinstance(value, str) and len(value) <= maximum and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)


def detect_media(content):
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise AppError("Seuls les originaux PDF, PNG et JPEG sont acceptés.", 415, "unsupported_document")


def validate_language(language):
    if not isinstance(language, str) or language not in LANGUAGES:
        raise AppError("Langue OCR invalide : eng, fra, spa ou fra+spa+eng.")
    return language


def document_risk_flags(extraction):
    """Preserve review triggers that must not disappear when fields are selected.

    These text matches identify possible complications, never a legal conclusion.
    A position map keeps the quotation exact despite accents or case folding.
    """
    result = []
    tax_rates = {}
    for page in extraction["pages"]:
        text, folded, positions = page["text"], [], []
        for index, character in enumerate(text):
            normalized = "".join(c for c in unicodedata.normalize("NFKD", character) if not unicodedata.combining(c)).casefold()
            folded.append(normalized)
            positions.extend([index] * len(normalized))
        flat = "".join(folded)
        for code, pattern in DOCUMENT_RISKS.items():
            found = re.search(pattern, flat)
            if found:
                start, end = positions[found.start()], positions[found.end() - 1] + 1
                result.append({"code": code, "page": page["number"], "quote": text[max(0, start - 80):min(len(text), end + 100)]})
        for found in re.finditer(r"\b(?:tva|vat|iva)\s*(?::|rate|taux|tipo)?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%", flat):
            start, end = positions[found.start()], positions[found.end() - 1] + 1
            rate = found.group(1).replace(",", ".")
            tax_rates.setdefault(float(rate), {"code": "multiple_tax_rates", "page": page["number"], "quote": text[max(0, start - 40):min(len(text), end + 60)]})
    if len(tax_rates) > 1:
        result.extend(list(tax_rates.values())[:5])
    return result


def _bbox(value):
    return (isinstance(value, list) and len(value) == 4 and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in value)
            and value[0] <= value[2] and value[1] <= value[3])


def validate_extraction(value, media_type):
    """Validate the worker as untrusted: no invented quote or cross-page reference."""
    try:
        if len(encoded(value).encode()) > MAX_EXTRACTION_BYTES:
            raise ValueError()
        if not isinstance(value, dict) or set(value) != {"version", "media_type", "pages", "candidates", "warnings", "engine", "review_required"}:
            raise ValueError()
        if type(value["version"]) is not int or value["version"] != 1 or value["media_type"] != media_type or value["review_required"] is not True:
            raise ValueError()
        pages = value["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 5 or (media_type != "application/pdf" and len(pages) != 1):
            raise ValueError()
        total_text, total_words = 0, 0
        for index, page in enumerate(pages, 1):
            if not isinstance(page, dict) or set(page) != {"number", "text", "method", "width", "height", "words"}:
                raise ValueError()
            if type(page["number"]) is not int or page["number"] != index or page["method"] not in {"native", "ocr"} or not _text(page["text"], 65536):
                raise ValueError()
            total_text += len(page["text"].encode())
            if any(type(page[key]) not in (int, float) or not math.isfinite(page[key]) or page[key] <= 0 for key in ("width", "height")):
                raise ValueError()
            if not isinstance(page["words"], list):
                raise ValueError()
            total_words += len(page["words"])
            for word in page["words"]:
                if not isinstance(word, dict) or set(word) != {"text", "bbox", "confidence"} or not _text(word["text"], 4096) or not _bbox(word["bbox"]):
                    raise ValueError()
                confidence = word["confidence"]
                if confidence is not None and (type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 100):
                    raise ValueError()
                if page["method"] == "native" and confidence is not None:
                    raise ValueError()
        if total_text > 65536 or total_words > 5000:
            raise ValueError()
        candidates = value["candidates"]
        if not isinstance(candidates, dict) or set(candidates) - CANDIDATE_FIELDS:
            raise ValueError()
        for candidate in candidates.values():
            if not isinstance(candidate, dict) or set(candidate) != {"value", "page", "quote", "bbox", "method"}:
                raise ValueError()
            if not _text(candidate["value"], 2000) or not candidate["value"] or type(candidate["page"]) is not int or not 1 <= candidate["page"] <= len(pages):
                raise ValueError()
            page = pages[candidate["page"] - 1]
            if (not _text(candidate["quote"], 2000) or not candidate["quote"] or candidate["quote"] not in page["text"]
                    or not _bbox(candidate["bbox"]) or candidate["method"] != page["method"]):
                raise ValueError()
        if not isinstance(value["warnings"], list) or len(value["warnings"]) > 30 or any(not _text(item, 1000) for item in value["warnings"]):
            raise ValueError()
        if not isinstance(value["engine"], dict) or len(encoded(value["engine"]).encode()) > 4096 or value["engine"].get("name") != "poppler+tesseract":
            raise ValueError()
        return value
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise AppError("Le résultat OCR est incomplet ou invalide. L'original reste disponible.", 502, "invalid_ocr_response") from exc


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OCRClient:
    """Fixed Compose service, never a caller-supplied URL or external provider."""
    def __init__(self, url):
        if url != "http://ocr:8766":
            raise ValueError("ADMIN_AGENT_OCR_URL doit être exactement http://ocr:8766.")
        self.url = url
        self.opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def extract(self, content, media_type, language, force_ocr=False):
        headers = {"Content-Type": media_type, "X-OCR-Language": language, "X-OCR-Force": "1" if force_ocr else "0", "Accept": "application/json"}
        req = request.Request(self.url + "/extract", data=content, headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=65) as response:
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise ValueError()
                raw = response.read(MAX_EXTRACTION_BYTES + 1)
                if len(raw) > MAX_EXTRACTION_BYTES:
                    raise ValueError()
            def pairs(items):
                result = {}
                for key, item in items:
                    if key in result:
                        raise ValueError()
                    result[key] = item
                return result
            def constant(_):
                raise ValueError()
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
            return validate_extraction(value, media_type)
        except error.HTTPError as exc:
            # Never propagate worker text, untrusted URLs or parser output.
            if exc.code in {400, 413, 422}:
                raise AppError("Document non exploitable ou limites OCR dépassées. Vérifiez l'original.", 422, "ocr_document_rejected") from exc
            raise AppError("Le service OCR est indisponible. Réessayez plus tard.", 503, "ocr_unavailable") from exc
        except AppError:
            raise
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise AppError("Le service OCR n'a pas fourni de résultat valide. Réessayez plus tard.", 503, "ocr_unavailable") from exc


class DocumentStore:
    def __init__(self, store, ocr_client=None, clock=time.time):
        self.store = store
        self.ocr = ocr_client
        self.clock = clock
        with store.connection() as con:
            # AuthStore must bind this database to a client before importing data.
            identity = con.execute("SELECT client_id FROM instance_identity WHERE singleton=1").fetchone()
            if identity is None:
                raise ValueError("L'identité client de la base est obligatoire.")
            self.client_id = identity[0]
            con.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL UNIQUE, content BLOB NOT NULL,
                    created_at TEXT NOT NULL, created_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'uploaded',
                    extraction_version INTEGER NOT NULL DEFAULT 0, extraction TEXT, language TEXT NOT NULL,
                    task_id TEXT REFERENCES tasks(id), task_request_hash TEXT, last_error TEXT,
                    extraction_token TEXT, extraction_until REAL
                );
                CREATE TABLE IF NOT EXISTS document_extractions (
                    document_id TEXT NOT NULL REFERENCES documents(id), version INTEGER NOT NULL,
                    body TEXT NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL,
                    PRIMARY KEY(document_id,version)
                );
                CREATE TABLE IF NOT EXISTS document_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL REFERENCES documents(id),
                    action TEXT NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL, details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS document_sources (
                    connector_id TEXT NOT NULL, source_key TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id),
                    fetched_at TEXT NOT NULL, PRIMARY KEY(connector_id,source_key)
                );
            """)

    def _guard(self, con):
        if con.execute("SELECT client_id FROM instance_identity WHERE singleton=1").fetchone()[0] != self.client_id:
            raise AppError("Identité de la base incohérente.", 409, "client_mismatch")
        guard = audit_guard.get()
        if guard is not None:
            guard(con)

    def _event(self, con, document_id, action, details=None):
        self._guard(con)
        if con.execute("SELECT count(*) FROM document_events").fetchone()[0] >= 10000:
            raise AppError("Capacité du journal documentaire atteinte.", 409, "capacity_reached")
        con.execute("INSERT INTO document_events(document_id,action,created_at,actor,details) VALUES(?,?,?,?,?)",
                    (document_id, action, now(), audit_actor.get(), encoded(details or {})))

    def _row(self, con, document_id):
        row = con.execute("SELECT " + METADATA_COLUMNS + ",extraction,extraction_token,extraction_until,task_request_hash FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise AppError("Document introuvable.", 404, "not_found")
        return row

    @staticmethod
    def _metadata(row, detail=False):
        doc = {key: row[key] for key in METADATA_COLUMNS.split(",")}
        if detail:
            doc["extraction"] = json.loads(row["extraction"]) if row["extraction"] else None
        return doc

    def list(self):
        with self.store.connection() as con:
            sources = {}
            for row in con.execute("SELECT DISTINCT document_id,connector_id FROM document_sources ORDER BY connector_id"):
                sources.setdefault(row["document_id"], []).append(row["connector_id"])
            return [dict(self._metadata(row), connector_ids=sources.get(row["id"], [])) for row in con.execute("SELECT " + METADATA_COLUMNS + " FROM documents ORDER BY created_at DESC,rowid DESC")]

    def get(self, document_id):
        with self.store.connection() as con:
            doc = self._metadata(self._row(con, document_id), detail=True)
            doc["sources"] = [dict(row) for row in con.execute("SELECT connector_id,source_key,fetched_at FROM document_sources WHERE document_id=?", (document_id,))]
            doc["events"] = [dict(row, details=json.loads(row["details"])) for row in con.execute("SELECT action,created_at,actor,details FROM document_events WHERE document_id=? ORDER BY id DESC LIMIT 100", (document_id,))]
            return doc

    def original(self, document_id):
        with self.store.connection() as con:
            row = self._row(con, document_id)
            content = con.execute("SELECT content FROM documents WHERE id=?", (document_id,)).fetchone()[0]
            return content, row["media_type"]

    def add(self, content, filename, declared_media_type=None, language="fra+spa+eng", source=None):
        validate_language(language)
        if not isinstance(content, bytes) or not content:
            raise AppError("Le document est vide.")
        if len(content) > MAX_FILE_BYTES:
            raise AppError("Le document dépasse 5 Mio.", 413, "document_too_large")
        media_type = detect_media(content)
        if declared_media_type not in {None, "", "application/octet-stream", media_type}:
            raise AppError("Le type déclaré ne correspond pas au document.", 415, "unsupported_document")
        if not _text(filename, 240) or not filename.strip() or any(unicodedata.category(c).startswith("C") for c in filename):
            raise AppError("Nom de fichier invalide.")
        filename = filename.replace("\\", "/").split("/")[-1].strip()
        if not filename or filename in {".", ".."}:
            raise AppError("Nom de fichier invalide.")
        if source is not None and (not isinstance(source, dict) or set(source) != {"connector_id", "source_key", "fetched_at"}
                or any(not _text(source[k], limit) or not source[k] for k, limit in (("connector_id", 100), ("source_key", 500), ("fetched_at", 100)))):
            raise AppError("Provenance du connecteur invalide.")
        digest = hashlib.sha256(content).hexdigest()
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            if source:
                previous = con.execute("SELECT d.id,d.sha256 FROM document_sources s JOIN documents d ON d.id=s.document_id WHERE s.connector_id=? AND s.source_key=?", (source["connector_id"], source["source_key"])).fetchone()
                if previous and previous["sha256"] != digest:
                    raise AppError("La pièce source a changé. Importez sa nouvelle version sous une référence explicite.", 409, "source_changed")
            row = con.execute("SELECT id FROM documents WHERE sha256=?", (digest,)).fetchone()
            created = row is None
            if created:
                count, size = con.execute("SELECT count(*),coalesce(sum(size_bytes),0) FROM documents").fetchone()
                if count >= MAX_DOCUMENTS or size + len(content) > MAX_TOTAL_BYTES:
                    raise AppError("Capacité documentaire atteinte. Contactez l'administrateur.", 409, "capacity_reached")
                document_id = str(uuid.uuid4())
                con.execute("INSERT INTO documents(id,filename,media_type,size_bytes,sha256,content,created_at,created_by,language) VALUES(?,?,?,?,?,?,?,?,?)",
                            (document_id, filename, media_type, len(content), digest, content, now(), audit_actor.get(), language))
                self._event(con, document_id, "document.uploaded", {"sha256": digest, "size_bytes": len(content)})
            else:
                document_id = row["id"]
            if source:
                existing = con.execute("SELECT 1 FROM document_sources WHERE connector_id=? AND source_key=?", (source["connector_id"], source["source_key"])).fetchone()
                if not existing:
                    if con.execute("SELECT count(*) FROM document_sources").fetchone()[0] >= 1000:
                        raise AppError("Capacité des références documentaires atteinte.", 409, "capacity_reached")
                    con.execute("INSERT INTO document_sources(connector_id,source_key,document_id,fetched_at) VALUES(?,?,?,?)", (source["connector_id"], source["source_key"], document_id, source["fetched_at"]))
                    self._event(con, document_id, "document.source_linked", {"connector_id": source["connector_id"]})
            return self._metadata(self._row(con, document_id), detail=True), created

    def extract(self, document_id, data):
        if self.ocr is None:
            raise AppError("Le service OCR n'est pas activé sur cette instance.", 503, "ocr_disabled")
        if not isinstance(data, dict) or set(data) - {"version", "language", "force_ocr"} or type(data.get("version")) is not int or type(data.get("force_ocr", False)) is not bool:
            raise AppError("Version documentaire et options OCR invalides.")
        language = validate_language(data.get("language", "fra+spa+eng"))
        token = str(uuid.uuid4())
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._row(con, document_id)
            if row["extraction_version"] != data["version"]:
                raise AppError("L'extraction a changé. Rechargez le document.", 409, "version_conflict")
            if row["extraction_version"] >= MAX_REVISIONS:
                raise AppError("Le document a atteint cinq versions d'extraction.", 409, "capacity_reached")
            if row["extraction_token"] and row["extraction_until"] > self.clock():
                raise AppError("Une extraction est déjà en cours.", 409, "extraction_busy")
            self._event(con, document_id, "document.extraction_started", {"language": language, "force_ocr": data.get("force_ocr", False)})
            con.execute("UPDATE documents SET status='extracting',extraction_token=?,extraction_until=?,last_error=NULL WHERE id=?", (token, self.clock() + 120, document_id))
            content = con.execute("SELECT content FROM documents WHERE id=?", (document_id,)).fetchone()[0]
            media_type = row["media_type"]
        try:
            result = validate_extraction(self.ocr.extract(content, media_type, language, data.get("force_ocr", False)), media_type)
            result_encoded = encoded(result)
            with self.store.connection() as con:
                con.execute("BEGIN IMMEDIATE")
                row = self._row(con, document_id)
                if row["extraction_token"] != token:
                    raise AppError("Une autre extraction a remplacé cette tentative.", 409, "version_conflict")
                size = con.execute("SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM document_extractions").fetchone()[0]
                if size + len(result_encoded.encode()) > MAX_EXTRACTION_TOTAL:
                    raise AppError("Capacité des extractions atteinte.", 409, "capacity_reached")
                version = row["extraction_version"] + 1
                self._event(con, document_id, "document.extracted", {"version": version, "pages": len(result["pages"])})
                con.execute("INSERT INTO document_extractions(document_id,version,body,created_at,actor) VALUES(?,?,?,?,?)", (document_id, version, result_encoded, now(), audit_actor.get()))
                con.execute("UPDATE documents SET status='extracted',extraction_version=?,extraction=?,language=?,extraction_token=NULL,extraction_until=NULL,last_error=NULL WHERE id=?", (version, result_encoded, language, document_id))
                return self._metadata(self._row(con, document_id), detail=True)
        except Exception as exc:
            # Recoverable failure; no raw parser/network exception persisted.
            with self.store.connection() as con:
                con.execute("BEGIN IMMEDIATE")
                row = self._row(con, document_id)
                if row["extraction_token"] == token:
                    self._event(con, document_id, "document.extraction_failed", {"code": exc.code if isinstance(exc, AppError) else "ocr_unavailable"})
                    con.execute("UPDATE documents SET status='failed',extraction_token=NULL,extraction_until=NULL,last_error=? WHERE id=?", (exc.code if isinstance(exc, AppError) else "ocr_unavailable", document_id))
            if isinstance(exc, AppError):
                raise
            raise AppError("L'extraction a échoué. L'original est conservé et peut être réessayé.", 503, "ocr_unavailable") from exc

    def create_task(self, document_id, data):
        allowed = {"title", "description", "skill_id", "country", "payload", "extraction_version", "human_verified", "verified_fields"}
        if not isinstance(data, dict) or set(data) - allowed or data.get("human_verified") is not True or type(data.get("extraction_version")) is not int:
            raise AppError("La version d'extraction et la confirmation humaine sont obligatoires.")
        task_data = {key: data[key] for key in ("title", "description", "skill_id", "country", "payload") if key in data}
        clean, _ = validate_task(task_data)
        if clean["skill_id"] not in {"invoice-check", "receivables-followup", "admin-triage", "expense-review"}:
            raise AppError("Ce type de dossier n'est pas pris en charge pour une pièce unique.")
        payload = clean["payload"]
        fields = data.get("verified_fields")
        allowed_fields = EXPENSE_FIELDS if clean["skill_id"] == "expense-review" else REVIEW_FIELDS
        if (not payload or set(payload) - allowed_fields or not isinstance(fields, list) or any(not isinstance(item, str) for item in fields)
                or len(fields) != len(set(fields)) or set(fields) != set(payload)
                or any(type(item) not in (str, bool) or (isinstance(item, str) and (not item.strip() or len(item) > 12000)) for item in payload.values())):
            raise AppError("Chaque champ conservé doit être renseigné et vérifié individuellement.")
        request_hash = hashlib.sha256(encoded({**clean, "extraction_version": data["extraction_version"], "verified_fields": sorted(fields)}).encode()).hexdigest()
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            row = self._row(con, document_id)
            if row["task_id"]:
                if row["task_request_hash"] != request_hash:
                    raise AppError("Un dossier existe déjà pour cet original. Modifiez ce dossier.", 409, "document_already_linked")
                return self.store._get(con, row["task_id"]), self._metadata(row, detail=True), False
            if row["status"] != "extracted" or row["extraction_version"] != data["extraction_version"]:
                raise AppError("Extrayez le document et relisez sa version actuelle avant de créer un dossier.", 409, "extraction_review_required")
            extraction = json.loads(row["extraction"])
            provenance = {"document_id": document_id, "sha256": row["sha256"], "extraction_version": row["extraction_version"],
                          "reviewed_by": audit_actor.get(), "reviewed_at": now(), "human_verified": True, "changed_since_document_review": [],
                          "document_risk_flags": document_risk_flags(extraction), "extraction_warnings": extraction["warnings"], "fields": {}}
            for key in sorted(payload):
                candidate = extraction["candidates"].get(key)
                provenance["fields"][key] = {"reviewed_value": payload[key], "origin": "candidate" if candidate else "manual",
                    "corrected": candidate is not None and candidate["value"] != payload[key], "candidate": candidate}
            clean["payload"] = dict(payload, _document_source=provenance)
            clean["idempotency_key"] = "document:" + document_id
            task, created = self.store._create(con, clean, allow_document_source=True)
            self._event(con, document_id, "document.task_created", {"task_id": task["id"], "version": row["extraction_version"], "verified_fields": sorted(fields)})
            con.execute("UPDATE documents SET task_id=?,task_request_hash=? WHERE id=?", (task["id"], request_hash, document_id))
            return task, self._metadata(self._row(con, document_id), detail=True), created

    def reverify_expense(self, document_id, data):
        """Explicitly reconfirm edited receipt facts; preserve original evidence."""
        receipt_fields = {"merchant", "expense_date", "total_amount", "currency"}
        if (not isinstance(data, dict) or set(data) != {"task_version", "extraction_version", "human_verified", "verified_fields"}
                or data["human_verified"] is not True or type(data["task_version"]) is not int or data["task_version"] < 1
                or type(data["extraction_version"]) is not int or data["extraction_version"] < 1
                or not isinstance(data["verified_fields"], list) or any(not isinstance(field, str) for field in data["verified_fields"])
                or len(data["verified_fields"]) != 4 or set(data["verified_fields"]) != receipt_fields):
            raise AppError("Reconfirmez individuellement marchand, date, total et devise avec les versions courantes.")
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            row = self._row(con, document_id)
            if not row["task_id"]:
                raise AppError("Aucun dossier n'est lié à ce reçu.", 409, "expense_task_required")
            task = self.store._get(con, row["task_id"])
            if task["skill_id"] != "expense-review":
                raise AppError("Cette confirmation est réservée aux notes de frais.", 409, "expense_task_required")
            if task["version"] != data["task_version"] or row["extraction_version"] != data["extraction_version"]:
                raise AppError("Le dossier ou l'extraction a changé. Rechargez avant de confirmer.", 409, "version_conflict")
            if row["status"] != "extracted":
                raise AppError("Une extraction terminée est nécessaire avant confirmation.", 409, "extraction_review_required")
            payload = task["payload"]
            source = payload.get("_document_source")
            if not isinstance(source, dict) or source.get("document_id") != document_id or source.get("sha256") != row["sha256"]:
                raise AppError("Le lien avec l'original n'est pas valide.", 409, "invalid_receipt_source")
            history = source.get("receipt_reviews", [])
            if not isinstance(history, list) or len(history) >= 10:
                raise AppError("Le reçu a atteint la limite de dix confirmations complémentaires.", 409, "capacity_reached")
            if any(not _text(payload.get(field), 1000) or not payload[field].strip() for field in receipt_fields):
                raise AppError("Renseignez les quatre faits du reçu dans le dossier avant de les confirmer.")
            extraction = json.loads(row["extraction"])
            review = {"reviewed_by": audit_actor.get(), "reviewed_at": now(), "human_verified": True,
                      "extraction_version": row["extraction_version"], "task_version": task["version"], "fields": {}}
            for field in sorted(receipt_fields):
                candidate = extraction["candidates"].get(field)
                review["fields"][field] = {"reviewed_value": payload[field], "origin": "candidate" if candidate else "manual",
                                           "corrected": candidate is not None and candidate["value"] != payload[field], "candidate": candidate}
            source = dict(source, receipt_reviews=[*history, review])
            # Retain newly observed risk evidence too; a second extraction must
            # never erase an earlier risk merely because OCR failed to read it.
            risks = list(source.get("document_risk_flags", []))
            for risk in document_risk_flags(extraction):
                if risk not in risks:
                    risks.append(risk)
            source["document_risk_flags"] = risks
            candidate = {key: task[key] for key in ("title", "description", "skill_id", "country", "payload")}
            candidate["payload"] = dict(payload, _document_source=source)
            clean, _ = validate_task(candidate)
            task.update(**clean, status="new", result=None, updated_at=now(), version=task["version"] + 1)
            con.execute("UPDATE tasks SET body=? WHERE id=?", (encoded(task), task["id"]))
            self.store._event(con, task["id"], "task.expense_reverified", {"document_id": document_id, "version": task["version"], "extraction_version": row["extraction_version"], "previous_review_invalidated": True})
            self._event(con, document_id, "document.expense_reverified", {"task_id": task["id"], "task_version": task["version"], "verified_fields": sorted(receipt_fields)})
            return task, self._metadata(row, detail=True)
