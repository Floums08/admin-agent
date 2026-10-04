"""Bounded invoice tracking, manual bank reconciliation and factoring estimates.

All amounts are decimal strings. Recording an observation never executes a bank
operation, assigns a receivable externally, or changes the approved source task.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
import csv
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
import re
import uuid

from .engine import CURRENCIES, analyze, result_status
from .errors import AppError
from .storage import audit_actor, audit_guard, encoded, now


MAX_INVOICES = 100
MAX_TRANSACTIONS = 1000
MAX_CSV_ROWS = 200
MAX_IMPORTS = 100
MAX_ALLOCATIONS = 3000
MAX_FINANCE_EVENTS = 10000
MAX_CSV_BYTES = 60000
CENT = Decimal("0.01")
CSV_FIELDS = ("transaction_id", "date", "amount", "currency", "reference")
SNAPSHOT_FIELDS = ("invoice_number", "supplier", "customer", "issue_date", "due_date", "total_amount", "currency")


def _schema(data, required, optional=()):
    if not isinstance(data, dict) or not set(required).issubset(data) or set(data) - set(required) - set(optional):
        raise AppError("Champs financiers manquants ou non pris en charge.", 400, "invalid_finance_input")


def _text(value, maximum=500, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or not empty and not value.strip() or any(ord(c) < 32 for c in value):
        raise AppError("Référence ou texte financier invalide.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AppError("Texte Unicode financier invalide.") from None
    return value.strip()


def _identifier(value):
    value = _text(value, 120)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", value):
        raise AppError("Identifiant financier invalide.")
    return value


def _money(value, *, signed=False, positive=False):
    pattern = r"[+-]?\d{1,12}(?:\.\d{1,2})?" if signed else r"\d{1,12}(?:\.\d{1,2})?"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise AppError("Montant attendu en texte décimal, sans séparateur de milliers, avec deux décimales maximum.")
    amount = Decimal(value)
    if positive and amount <= 0:
        raise AppError("Le montant doit être strictement positif.")
    return amount


def _rate(value):
    amount = _money(value)
    if amount > 100:
        raise AppError("Le taux doit être compris entre 0 et 100.")
    return amount


def _fmt(value):
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def _cents(value):
    return int(value * 100)


def _date(value, *, past=False):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AppError("Date attendue au format AAAA-MM-JJ.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AppError("Date financière impossible.") from None
    if past and parsed > date.today():
        raise AppError("La date de preuve ou d'opération ne peut pas être dans le futur.")
    return parsed


def _version(value, expected):
    if type(value) is not int or value < 1:
        raise AppError("La version relue est obligatoire.")
    if value != expected:
        raise AppError("Les données financières ont changé. Rechargez-les avant de confirmer.", 409, "version_conflict")


def _currency(value):
    if not isinstance(value, str) or value not in CURRENCIES:
        raise AppError("Devise à deux décimales non prise en charge.")
    return value


class FinanceStore:
    def __init__(self, store):
        self.store = store
        with store.connection() as con:
            self.client_id = self._identity(con)
            con.executescript("""
                CREATE TABLE IF NOT EXISTS finance_invoices (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
                    business_key TEXT NOT NULL UNIQUE, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS finance_bank_transactions (
                    id TEXT PRIMARY KEY, account_ref TEXT NOT NULL, external_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(account_ref, external_id)
                );
                CREATE TABLE IF NOT EXISTS finance_allocations (
                    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES finance_invoices(id),
                    transaction_id TEXT NOT NULL REFERENCES finance_bank_transactions(id),
                    amount_cents INTEGER NOT NULL CHECK(amount_cents>0), active INTEGER NOT NULL CHECK(active IN (0,1)),
                    request_key TEXT NOT NULL UNIQUE, body TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS finance_allocation_invoice ON finance_allocations(invoice_id,active);
                CREATE INDEX IF NOT EXISTS finance_allocation_transaction ON finance_allocations(transaction_id,active);
                CREATE TABLE IF NOT EXISTS finance_bank_imports (
                    id TEXT PRIMARY KEY, preview_digest TEXT NOT NULL UNIQUE, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS finance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL, action TEXT NOT NULL,
                    created_at TEXT NOT NULL, actor TEXT NOT NULL, details TEXT NOT NULL
                );
            """)

    @staticmethod
    def _identity(con):
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instance_identity'").fetchone():
            return None
        row = con.execute("SELECT client_id FROM instance_identity WHERE singleton=1").fetchone()
        return row[0] if row else None

    def _identity_guard(self, con):
        if self._identity(con) != self.client_id:
            raise AppError("Identité de la base financière incohérente.", 409, "client_mismatch")

    def _guard(self, con):
        self._identity_guard(con)
        guard = audit_guard.get()
        if guard is not None:
            guard(con)

    def _event(self, con, entity_id, action, details=None):
        self._guard(con)
        if con.execute("SELECT count(*) FROM finance_events").fetchone()[0] >= MAX_FINANCE_EVENTS:
            raise AppError("Capacité du journal financier atteinte.", 409, "capacity_reached")
        con.execute("INSERT INTO finance_events(entity_id,action,created_at,actor,details) VALUES(?,?,?,?,?)",
                    (entity_id, action, now(), audit_actor.get(), encoded(dict(details or {}, outbound_executed=False))))

    @staticmethod
    def _body(con, table, identifier):
        _identifier(identifier)
        row = con.execute(f"SELECT body FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise AppError("Élément financier introuvable.", 404, "not_found")
        return json.loads(row["body"])

    @staticmethod
    def _save(con, table, item):
        con.execute(f"UPDATE {table} SET body=? WHERE id=?", (encoded(item), item["id"]))

    def _invoice(self, con, identifier):
        item = self._body(con, "finance_invoices", identifier)
        task = self.store._get(con, item["task_id"])
        item["source_stale"] = task["version"] != item["task_version"] or task["status"] != "ready" or any(
            task["payload"].get(key) != item["source_snapshot"][key] for key in SNAPSHOT_FIELDS)
        cents = con.execute("SELECT COALESCE(sum(amount_cents),0) FROM finance_allocations WHERE invoice_id=? AND active=1", (identifier,)).fetchone()[0]
        allocated = Decimal(cents) / 100
        paid = Decimal(item["opening_paid_amount"]) + allocated
        remaining = Decimal(item["total_amount"]) - paid
        item.update(allocated_amount=_fmt(allocated), paid_amount=_fmt(paid), remaining_amount=_fmt(remaining),
                    payment_status="paid" if remaining == 0 else "partial" if paid > 0 else "unpaid",
                    overdue=remaining > 0 and date.fromisoformat(item["due_date"]) < date.today(),
                    days_overdue=max(0, (date.today() - date.fromisoformat(item["due_date"])).days) if remaining > 0 else 0)
        item["can_allocate"] = not item["source_stale"] and remaining > 0 and item["assignment_status"] != "assigned"
        return item

    def _transaction(self, con, identifier):
        item = self._body(con, "finance_bank_transactions", identifier)
        cents = con.execute("SELECT COALESCE(sum(amount_cents),0) FROM finance_allocations WHERE transaction_id=? AND active=1", (identifier,)).fetchone()[0]
        allocated = Decimal(cents) / 100
        item.update(allocated_amount=_fmt(allocated), remaining_amount=_fmt(abs(Decimal(item["amount"])) - allocated))
        return item

    @staticmethod
    def _clean_invoice(item):
        return {key: value for key, value in item.items() if key != "source_snapshot"}

    def register_invoice(self, data):
        _schema(data, {"task_id", "task_version", "direction", "opening_paid_amount", "opening_as_of", "opening_confirmed", "evidence_ref", "disputed"})
        _identifier(data["task_id"])
        if data["direction"] not in ("receivable", "payable") or data["opening_confirmed"] is not True:
            raise AppError("Le sens et la confirmation explicite du solde d'ouverture sont obligatoires.")
        if type(data["disputed"]) is not bool and data["disputed"] != "unknown":
            raise AppError("Le litige doit être true, false ou 'unknown'.")
        opening = _money(data["opening_paid_amount"])
        opening_date = _date(data["opening_as_of"], past=True)
        evidence = _text(data["evidence_ref"])
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            task = self.store._get(con, data["task_id"])
            _version(data["task_version"], task["version"])
            if task["skill_id"] != "invoice-check" or task["status"] != "ready" or result_status(analyze(task)) == "blocked":
                raise AppError("Seule une facture simple analysée et validée, sans blocage actuel, peut entrer dans le suivi.", 409, "invoice_source_not_ready")
            payload = task["payload"]
            total = _money(payload["total_amount"], positive=True)
            if opening > total:
                raise AppError("Le montant déjà payé ne peut dépasser le montant de la facture.")
            if opening_date < _date(payload["issue_date"]):
                raise AppError("La preuve du solde ne peut précéder l'émission de la facture.")
            if payload.get("paid") is True and opening != total:
                raise AppError("La source indique une facture payée : corriger et revalider la source avant d'ouvrir un solde restant.", 409, "payment_state_conflict")
            business_key = hashlib.sha256(encoded([data["direction"], task["country"], *[payload[key].strip().casefold() for key in ("supplier", "customer", "invoice_number")]]).encode()).hexdigest()
            if con.execute("SELECT 1 FROM finance_invoices WHERE task_id=? OR business_key=?", (task["id"], business_key)).fetchone():
                raise AppError("Cette facture ou son identité métier figure déjà dans le suivi.", 409, "invoice_already_registered")
            if con.execute("SELECT count(*) FROM finance_invoices").fetchone()[0] >= MAX_INVOICES:
                raise AppError("Limite de 100 factures suivies atteinte.", 409, "capacity_reached")
            item = dict(id=str(uuid.uuid4()), task_id=task["id"], task_version=task["version"], country=task["country"], direction=data["direction"],
                        **{key: payload[key] for key in SNAPSHOT_FIELDS}, source_snapshot={key: payload[key] for key in SNAPSHOT_FIELDS},
                        opening_paid_amount=_fmt(opening), opening_as_of=opening_date.isoformat(), evidence_ref=evidence, disputed=data["disputed"],
                        version=1, assignment_status="none", assignment=None, created_at=now(), updated_at=now())
            item["total_amount"] = _fmt(total)
            con.execute("INSERT INTO finance_invoices(id,task_id,business_key,body) VALUES(?,?,?,?)", (item["id"], task["id"], business_key, encoded(item)))
            self._event(con, item["id"], "finance.invoice_registered", {"task_id": task["id"], "task_version": task["version"], "direction": data["direction"], "opening_paid_amount": _fmt(opening), "opening_as_of": opening_date.isoformat(), "evidence_ref": evidence})
            return self._clean_invoice(self._invoice(con, item["id"]))

    def list_invoices(self):
        with self.store.connection() as con:
            self._identity_guard(con)
            return [self._clean_invoice(self._invoice(con, row["id"])) for row in con.execute("SELECT id FROM finance_invoices ORDER BY rowid DESC").fetchall()]

    def list_transactions(self):
        with self.store.connection() as con:
            self._identity_guard(con)
            return [self._transaction(con, row["id"]) for row in con.execute("SELECT id FROM finance_bank_transactions ORDER BY rowid DESC").fetchall()]

    def list_allocations(self):
        with self.store.connection() as con:
            self._identity_guard(con)
            return [json.loads(row["body"]) for row in con.execute("SELECT body FROM finance_allocations ORDER BY rowid DESC")]

    def _parse_bank(self, data, committing=False):
        _schema(data, {"account_ref", "csv_text", *({"preview_digest"} if committing else set())})
        account = _identifier(data["account_ref"])
        source = data["csv_text"]
        if not isinstance(source, str):
            raise AppError("Le CSV bancaire doit être un texte UTF-8.")
        try:
            size = len(source.encode("utf-8"))
        except UnicodeError:
            raise AppError("Le texte CSV n'est pas un UTF-8 valide.") from None
        if not source or size > MAX_CSV_BYTES or "\x00" in source:
            raise AppError("Le CSV doit contenir entre 1 et 60 000 octets, sans caractère nul.", 413, "csv_too_large")
        try:
            reader = csv.reader(io.StringIO(source.lstrip("\ufeff"), newline=""), strict=True)
            header = next(reader)
            if tuple(header) != CSV_FIELDS:
                raise AppError("En-tête CSV exact requis : transaction_id,date,amount,currency,reference (séparateur virgule).")
            rows, unique = [], {}
            for number, values in enumerate(reader, 1):
                if number > MAX_CSV_ROWS:
                    raise AppError("Le lot CSV dépasse 200 lignes.", 413, "csv_too_large")
                if len(values) != len(CSV_FIELDS):
                    raise AppError("Chaque ligne bancaire doit contenir exactement cinq colonnes.")
                row = dict(zip(CSV_FIELDS, values))
                row["transaction_id"] = _identifier(row["transaction_id"])
                row["date"] = _date(row["date"], past=True).isoformat()
                amount = _money(row["amount"], signed=True)
                if amount == 0:
                    raise AppError("Une transaction bancaire nulle ne peut pas être rapprochée.")
                row.update(amount=_fmt(amount), currency=_currency(row["currency"]), reference=_text(row["reference"], 500, empty=True), account_ref=account)
                content_hash = hashlib.sha256(encoded(row).encode()).hexdigest()
                previous = unique.get(row["transaction_id"])
                if previous is not None and previous != content_hash:
                    raise AppError("Même identifiant bancaire avec des contenus différents dans le lot.", 409, "bank_id_conflict")
                if previous is not None:
                    raise AppError("Une transaction apparaît plusieurs fois dans le même CSV. Supprimez le doublon avant import.", 409, "bank_duplicate_in_batch")
                unique[row["transaction_id"]] = content_hash
                rows.append((row, content_hash))
            if not rows:
                raise AppError("Le CSV ne contient aucune transaction.")
        except (csv.Error, StopIteration):
            raise AppError("Le CSV bancaire est mal formé.") from None
        digest = hashlib.sha256(encoded({"account_ref": account, "rows": [row for row, _ in rows]}).encode()).hexdigest()
        if committing and (not isinstance(data["preview_digest"], str) or data["preview_digest"] != digest):
            raise AppError("Le CSV a changé depuis l'aperçu. Générer et relire un nouvel aperçu.", 409, "preview_changed")
        return rows, digest

    def _bank_preview(self, con, rows, digest):
        output, duplicates = [], 0
        for row, content_hash in rows:
            existing = con.execute("SELECT content_hash FROM finance_bank_transactions WHERE account_ref=? AND external_id=?", (row["account_ref"], row["transaction_id"])).fetchone()
            if existing is not None and existing[0] != content_hash:
                raise AppError("Une transaction existe déjà avec un contenu différent ; aucun élément du lot n'a été importé.", 409, "bank_id_conflict")
            duplicates += existing is not None
            output.append(dict(row, state="duplicate" if existing else "new"))
        if con.execute("SELECT count(*) FROM finance_bank_transactions").fetchone()[0] + len(rows) - duplicates > MAX_TRANSACTIONS:
            raise AppError("Limite de 1 000 transactions bancaires atteinte.", 409, "capacity_reached")
        return {"preview_digest": digest, "row_count": len(rows), "new_count": len(rows) - duplicates, "duplicate_count": duplicates,
                "rows": output, "outbound_executed": False}

    def preview_bank(self, data):
        rows, digest = self._parse_bank(data)
        with self.store.connection() as con:
            self._identity_guard(con)
            return self._bank_preview(con, rows, digest)

    def import_bank(self, data):
        rows, digest = self._parse_bank(data, committing=True)
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            preview = self._bank_preview(con, rows, digest)
            if preview["new_count"] and con.execute("SELECT count(*) FROM finance_bank_imports").fetchone()[0] >= MAX_IMPORTS:
                raise AppError("Limite de 100 imports bancaires atteinte.", 409, "capacity_reached")
            transactions = []
            for row, content_hash in rows:
                existing = con.execute("SELECT id FROM finance_bank_transactions WHERE account_ref=? AND external_id=?", (row["account_ref"], row["transaction_id"])).fetchone()
                if existing:
                    transactions.append(self._transaction(con, existing[0]))
                    continue
                item = dict(row, id=str(uuid.uuid4()), version=1, created_at=now(), content_sha256=content_hash)
                con.execute("INSERT INTO finance_bank_transactions(id,account_ref,external_id,content_hash,body) VALUES(?,?,?,?,?)",
                            (item["id"], item["account_ref"], item["transaction_id"], content_hash, encoded(item)))
                transactions.append(self._transaction(con, item["id"]))
            if preview["new_count"]:
                source = dict(id=str(uuid.uuid4()), account_ref=data["account_ref"], preview_digest=digest, row_count=len(rows), imported_count=preview["new_count"],
                              csv_text=data["csv_text"], source_sha256=hashlib.sha256(data["csv_text"].encode()).hexdigest(), imported_at=now(), actor=audit_actor.get())
                con.execute("INSERT INTO finance_bank_imports(id,preview_digest,body) VALUES(?,?,?)", (source["id"], digest, encoded(source)))
                self._event(con, source["id"], "finance.bank_imported", {"account_ref": data["account_ref"], "created": preview["new_count"], "duplicates": preview["duplicate_count"], "source_sha256": source["source_sha256"], "preview_digest": digest})
            return {"created": preview["new_count"], "duplicates": preview["duplicate_count"], "transactions": transactions, "outbound_executed": False}

    @staticmethod
    def _allocation_compatible(invoice, transaction):
        if invoice["source_stale"]:
            raise AppError("Le dossier source a changé : rapprochement bloqué pour vérification manuelle.", 409, "invoice_source_stale")
        if invoice["assignment_status"] == "assigned":
            raise AppError("Créance déclarée cédée : traiter les flux du factor séparément des paiements clients.", 409, "invoice_assigned")
        if invoice["currency"] != transaction["currency"]:
            raise AppError("Les devises de la facture et de la transaction sont différentes.", 409, "currency_mismatch")
        if (invoice["direction"] == "receivable") != (Decimal(transaction["amount"]) > 0):
            raise AppError("Le sens de la transaction ne correspond pas au type de facture.", 409, "direction_mismatch")
        if transaction["date"] <= invoice["opening_as_of"]:
            raise AppError("Cette opération est antérieure ou égale au solde d'ouverture en fin de journée ; risque de double comptage.", 409, "transaction_before_opening")
        if re.search(r"\b(factoring|factor|affacturage|financement|financing)\b", transaction["reference"], re.IGNORECASE):
            raise AppError("Flux de financement présumé : ne pas le comptabiliser comme paiement du débiteur.", 409, "financing_not_payment")

    def confirm_allocation(self, data):
        _schema(data, {"invoice_id", "invoice_version", "transaction_id", "transaction_version", "amount", "evidence_ref", "idempotency_key"})
        amount = _money(data["amount"], positive=True)
        evidence = _text(data["evidence_ref"])
        key = _identifier(data["idempotency_key"])
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            if con.execute("SELECT 1 FROM finance_allocations WHERE request_key=?", (key,)).fetchone():
                raise AppError("Cette confirmation a déjà été enregistrée ; elle ne peut pas être rejouée.", 409, "allocation_replay")
            invoice = self._invoice(con, data["invoice_id"])
            transaction = self._transaction(con, data["transaction_id"])
            _version(data["invoice_version"], invoice["version"])
            _version(data["transaction_version"], transaction["version"])
            self._allocation_compatible(invoice, transaction)
            if amount > Decimal(invoice["remaining_amount"]) or amount > Decimal(transaction["remaining_amount"]):
                raise AppError("L'affectation dépasse le solde disponible de la facture ou de la transaction.", 409, "over_allocation")
            if con.execute("SELECT count(*) FROM finance_allocations").fetchone()[0] >= MAX_ALLOCATIONS:
                raise AppError("Limite de 3 000 affectations historiques atteinte.", 409, "capacity_reached")
            allocation = dict(id=str(uuid.uuid4()), invoice_id=invoice["id"], transaction_id=transaction["id"], amount=_fmt(amount),
                              currency=invoice["currency"], version=1, status="active", evidence_ref=evidence,
                              created_at=now(), created_by=audit_actor.get(), reversed_at=None, reverse_reason=None)
            con.execute("INSERT INTO finance_allocations(id,invoice_id,transaction_id,amount_cents,active,request_key,body) VALUES(?,?,?,?,1,?,?)",
                        (allocation["id"], invoice["id"], transaction["id"], _cents(amount), key, encoded(allocation)))
            for table, identifier in (("finance_invoices", invoice["id"]), ("finance_bank_transactions", transaction["id"])):
                item = self._body(con, table, identifier)
                item.update(version=item["version"] + 1, updated_at=now())
                self._save(con, table, item)
            self._event(con, allocation["id"], "finance.allocation_confirmed", {"invoice_id": invoice["id"], "transaction_id": transaction["id"], "amount": _fmt(amount), "currency": invoice["currency"], "evidence_ref": evidence})
            return allocation

    def reverse_allocation(self, allocation_id, data):
        _schema(data, {"version", "invoice_version", "transaction_version", "reason"})
        reason = _text(data["reason"])
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            allocation = self._body(con, "finance_allocations", allocation_id)
            _version(data["version"], allocation["version"])
            invoice = self._invoice(con, allocation["invoice_id"])
            transaction = self._transaction(con, allocation["transaction_id"])
            _version(data["invoice_version"], invoice["version"])
            _version(data["transaction_version"], transaction["version"])
            if allocation["status"] != "active":
                raise AppError("Cette affectation a déjà été annulée.", 409, "allocation_already_reversed")
            # A corrective reversal remains possible even when the source is stale or assigned.
            allocation.update(status="reversed", version=allocation["version"] + 1, reversed_at=now(), reverse_reason=reason, reversed_by=audit_actor.get())
            con.execute("UPDATE finance_allocations SET active=0,body=? WHERE id=?", (encoded(allocation), allocation_id))
            for table, identifier in (("finance_invoices", invoice["id"]), ("finance_bank_transactions", transaction["id"])):
                item = self._body(con, table, identifier)
                item.update(version=item["version"] + 1, updated_at=now())
                self._save(con, table, item)
            self._event(con, allocation_id, "finance.allocation_reversed", {"invoice_id": invoice["id"], "transaction_id": transaction["id"], "amount": allocation["amount"], "reason": reason})
            return allocation

    def suggestions(self):
        with self.store.connection() as con:
            self._identity_guard(con)
            invoices = [self._invoice(con, row[0]) for row in con.execute("SELECT id FROM finance_invoices").fetchall()]
            transactions = [self._transaction(con, row[0]) for row in con.execute("SELECT id FROM finance_bank_transactions").fetchall()]
            suggestions, manual = [], []
            for transaction in transactions:
                if Decimal(transaction["remaining_amount"]) <= 0:
                    continue
                candidates = []
                for invoice in invoices:
                    if not invoice["can_allocate"] or invoice["disputed"] is not False:
                        continue
                    try:
                        self._allocation_compatible(invoice, transaction)
                    except AppError:
                        continue
                    candidates.append(invoice)
                matches = [item for item in candidates if re.search(r"(?<![\w/.-])" + re.escape(item["invoice_number"]) + r"(?![\w/.-])", transaction["reference"], re.IGNORECASE)]
                if len(matches) == 1:
                    invoice = matches[0]
                    amount = min(Decimal(invoice["remaining_amount"]), Decimal(transaction["remaining_amount"]))
                    suggestions.append({"invoice_id": invoice["id"], "transaction_id": transaction["id"], "amount": _fmt(amount),
                                        "reason": "reference_and_amount" if invoice["remaining_amount"] == transaction["remaining_amount"] else "reference_partial",
                                        "invoice_version": invoice["version"], "transaction_version": transaction["version"]})
                elif len(matches) > 1:
                    manual.append({"transaction_id": transaction["id"], "reason": "ambiguous_reference", "candidate_invoice_ids": [item["id"] for item in matches]})
                else:
                    same_amount = [item["id"] for item in candidates if item["remaining_amount"] == transaction["remaining_amount"]]
                    if same_amount:
                        manual.append({"transaction_id": transaction["id"], "reason": "amount_only", "candidate_invoice_ids": same_amount})
            return {"suggestions": suggestions, "manual_only": manual, "auto_allocated": False}

    def set_assignment(self, invoice_id, data):
        _schema(data, {"version", "status", "effective_date", "evidence_ref", "note"})
        if data["status"] not in ("assigned", "released"):
            raise AppError("État de cession documenté attendu : assigned ou released.")
        effective = _date(data["effective_date"], past=True)
        evidence, note = _text(data["evidence_ref"]), _text(data["note"])
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            invoice = self._invoice(con, invoice_id)
            _version(data["version"], invoice["version"])
            if invoice["direction"] != "receivable":
                raise AppError("Le suivi de cession ne s'applique qu'aux factures clients.")
            if invoice["source_stale"]:
                raise AppError("La source a changé ; relecture spécifique nécessaire.", 409, "invoice_source_stale")
            if data["status"] == "assigned":
                if invoice["assignment_status"] == "assigned" or Decimal(invoice["paid_amount"]) != 0 or invoice["disputed"] is not False:
                    raise AppError("La cession ne peut être notée sur une facture déjà cédée, payée partiellement ou litigieuse/inconnue.", 409, "assignment_blocked")
            elif invoice["assignment_status"] != "assigned":
                raise AppError("Aucune cession active à lever.", 409, "assignment_blocked")
            elif effective.isoformat() < invoice["assignment"]["effective_date"]:
                raise AppError("La levée ne peut précéder la date de cession documentée.")
            if effective < _date(invoice["issue_date"]):
                raise AppError("La date de cession ne peut précéder la facture.")
            item = self._body(con, "finance_invoices", invoice_id)
            item.update(assignment_status=data["status"], assignment={"effective_date": effective.isoformat(), "evidence_ref": evidence, "note": note, "recorded_by": audit_actor.get(), "recorded_at": now(), "external_action_executed": False}, version=item["version"] + 1, updated_at=now())
            self._save(con, "finance_invoices", item)
            self._event(con, invoice_id, "finance.assignment_documented", {"status": data["status"], "effective_date": effective.isoformat(), "evidence_ref": evidence, "note": note, "not_a_payment": True})
            return self._clean_invoice(self._invoice(con, invoice_id))

    def set_invoice_state(self, invoice_id, data):
        _schema(data, {"version", "disputed", "confirmed_on", "evidence_ref", "note"})
        disputed = "unknown" if data["disputed"] is None else data["disputed"]
        if type(disputed) is not bool and disputed != "unknown":
            raise AppError("Le litige doit être true, false ou inconnu.")
        confirmed = _date(data["confirmed_on"], past=True)
        evidence, note = _text(data["evidence_ref"]), _text(data["note"])
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            item = self._body(con, "finance_invoices", invoice_id)
            _version(data["version"], item["version"])
            if confirmed < _date(item["issue_date"]):
                raise AppError("La preuve du litige ne peut précéder la facture.")
            item.update(disputed=disputed, dispute_evidence={"confirmed_on": confirmed.isoformat(), "evidence_ref": evidence, "note": note},
                        version=item["version"] + 1, updated_at=now())
            self._save(con, "finance_invoices", item)
            self._event(con, invoice_id, "finance.dispute_state_documented", {"disputed": disputed, "confirmed_on": confirmed.isoformat(), "evidence_ref": evidence, "note": note})
            return self._clean_invoice(self._invoice(con, invoice_id))

    def simulate_factoring(self, data):
        _schema(data, {"invoice_id", "invoice_version", "advance_rate", "fee_rate", "annual_interest_rate", "fixed_fee", "funding_date", "day_basis"})
        advance_rate, fee_rate, interest_rate = [_rate(data[key]) for key in ("advance_rate", "fee_rate", "annual_interest_rate")]
        fixed_fee = _money(data["fixed_fee"])
        funding = _date(data["funding_date"])
        if type(data["day_basis"]) is not int or data["day_basis"] not in (360, 365) or advance_rate == 0:
            raise AppError("Base de jours 360 ou 365 et taux d'avance strictement positif requis.")
        if funding < date.today():
            raise AppError("La date de financement simulée ne peut être passée.")
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            self._guard(con)
            invoice = self._invoice(con, data["invoice_id"])
            _version(data["invoice_version"], invoice["version"])
            due = _date(invoice["due_date"])
            if (invoice["source_stale"] or invoice["direction"] != "receivable" or invoice["disputed"] is not False
                    or invoice["assignment_status"] == "assigned" or Decimal(invoice["paid_amount"]) != 0 or funding >= due):
                raise AppError("Simulation limitée aux créances clients entièrement impayées, non litigieuses, non cédées, source inchangée et échéance future.", 409, "factoring_blocked")
            nominal = Decimal(invoice["remaining_amount"])
            advance = (nominal * advance_rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
            reserve = nominal - advance
            fees = (nominal * fee_rate / 100 + fixed_fee).quantize(CENT, rounding=ROUND_HALF_UP)
            days = (due - funding).days
            interest = (advance * interest_rate / 100 * days / data["day_basis"]).quantize(CENT, rounding=ROUND_HALF_UP)
            net_cash = advance - fees - interest
            if net_cash < 0:
                raise AppError("Les frais et intérêts dépassent l'avance ; aucun net disponible positif n'est simulable.")
            simulation = {"invoice_id": invoice["id"], "invoice_version": invoice["version"], "currency": invoice["currency"],
                          "nominal": _fmt(nominal), "advance": _fmt(advance), "reserve": _fmt(reserve), "fees": _fmt(fees),
                          "interest": _fmt(interest), "total_cost": _fmt(fees + interest), "net_cash": _fmt(net_cash),
                          "advance_rate": _fmt(advance_rate), "fee_rate": _fmt(fee_rate), "annual_interest_rate": _fmt(interest_rate), "fixed_fee": _fmt(fixed_fee),
                          "days": days, "day_basis": data["day_basis"], "funding_date": funding.isoformat(), "maturity_date": due.isoformat(),
                          "balance_evidence_as_of": invoice["opening_as_of"], "indicative": True, "external_offer": False, "outbound_executed": False,
                          "assumptions": ["Taux et frais saisis par l'opérateur, pas des prix de marché.", "Frais prélevés immédiatement ; intérêts simples sur l'avance pour la durée saisie.",
                                          "La réserve est indisponible et n'est pas un coût ; sa libération dépend du contrat et du paiement du débiteur.",
                                          "TVA sur frais, minimums, garanties, commissions annexes, retard et recours exclus : vérifier une offre réelle.",
                                          "Aucune éligibilité financeur, cession, avance ou paiement n'est confirmé ; vérifier les encaissements depuis la date de preuve."]}
            self._event(con, invoice["id"], "finance.factoring_simulated", simulation)
            return simulation

    def summary(self):
        with self.store.connection() as con:
            con.execute("BEGIN")
            self._identity_guard(con)
            invoices = [self._invoice(con, row[0]) for row in con.execute("SELECT id FROM finance_invoices").fetchall()]
            transactions_count = con.execute("SELECT count(*) FROM finance_bank_transactions").fetchone()[0]
            allocations_count = con.execute("SELECT count(*) FROM finance_allocations").fetchone()[0]
        buckets = defaultdict(lambda: {name: Decimal(0) for name in ("receivable_remaining", "payable_remaining", "receivable_overdue", "payable_overdue")})
        for invoice in invoices:
            bucket = buckets[invoice["currency"]]
            bucket[invoice["direction"] + "_remaining"] += Decimal(invoice["remaining_amount"])
            if invoice["overdue"]:
                bucket[invoice["direction"] + "_overdue"] += Decimal(invoice["remaining_amount"])
        return {"invoices_count": len(invoices), "transactions_count": transactions_count, "allocations_count": allocations_count,
                "by_currency": [{"currency": currency, **{key: _fmt(value) for key, value in amounts.items()}} for currency, amounts in sorted(buckets.items())],
                "warnings": ["Montants issus du suivi saisi, pas un solde bancaire ni une comptabilité certifiée."] + (["Des factures ont une source modifiée ; leurs soldes doivent être vérifiés."] if any(invoice["source_stale"] for invoice in invoices) else []), "outbound_enabled": False}

    def export(self, connection=None):
        with self.store.connection() if connection is None else nullcontext(connection) as con:
            self._identity_guard(con)
            if connection is None:
                con.execute("BEGIN")
            return {"format_version": "1.0", "outbound_executed": False,
                    "invoices": [self._clean_invoice(self._invoice(con, row[0])) for row in con.execute("SELECT id FROM finance_invoices").fetchall()],
                    "transactions": [self._transaction(con, row[0]) for row in con.execute("SELECT id FROM finance_bank_transactions").fetchall()],
                    "allocations": [json.loads(row[0]) for row in con.execute("SELECT body FROM finance_allocations")],
                    "bank_imports": [json.loads(row[0]) for row in con.execute("SELECT body FROM finance_bank_imports")],
                    "events": [dict(row, details=json.loads(row["details"])) for row in con.execute("SELECT id,entity_id,action,created_at,actor,details FROM finance_events ORDER BY id")]}
