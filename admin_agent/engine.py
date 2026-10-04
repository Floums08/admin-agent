"""Deterministic checks. No external action and no implicit legal conclusions."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata

from .catalog import context_manifest, get_skill


MONEY = re.compile(r"^\d{1,12}(?:\.\d{1,2})?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENCIES = {"EUR", "USD", "GBP", "CHF", "CAD", "AUD"}
CENT = Decimal("0.01")
DOCUMENT_RISK_MESSAGES = {
    "partial_payment": "La pièce évoque un acompte ou un paiement partiel. Le solde doit être rapproché manuellement avant tout contrôle final ou préparation de relance.",
    "credit_note": "La pièce évoque un avoir ou une correction de facture. Ce cas dépasse le contrôle d'une facture simple et nécessite une revue spécialisée.",
    "special_vat": "La pièce évoque un traitement de TVA particulier. Son applicabilité doit être vérifiée par le responsable compétent ; aucun régime n'est déduit automatiquement.",
    "bank_change": "La pièce évoque des coordonnées bancaires nouvelles ou modifiées. Faire vérifier le bénéficiaire par un canal indépendant avant validation.",
    "retention": "La pièce évoque une retenue. Ce cas dépasse le calcul d'une facture simple ; faire vérifier les montants et le solde par le responsable compétent.",
    "multiple_tax_rates": "La pièce indique plusieurs taux de TVA. Le moteur à un seul taux ne peut pas conclure ; faire contrôler le détail de la facture.",
}


class CheckResult:
    def __init__(self):
        self.value = dict(summary="", findings=[], missing_fields=[], draft="", checks=[], mode="offline")

    def finding(self, severity, message, field=None):
        item = dict(severity=severity, message=message)
        if field is not None:
            item["field"] = field
        self.value["findings"].append(item)

    def check(self, name, passed, detail):
        self.value["checks"].append(dict(name=name, passed=passed, detail=detail))

    def missing(self, name):
        if name not in self.value["missing_fields"]:
            self.value["missing_fields"].append(name)
            self.finding("error", f"Information obligatoire manquante : {name}.", name)

    def required(self, payload, name):
        value = payload.get(name)
        if value is None or isinstance(value, str) and not value.strip():
            self.missing(name)
            return None
        return value

    def text(self, payload, name, prefix=""):
        value = self.required(payload, name)
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 1000:
            self.finding("error", f"{prefix + name} doit être un texte de 1 à 1 000 caractères.", prefix + name)
            return None
        return value.strip()

    def boolean(self, payload, name):
        value = self.required(payload, name)
        if value is not None and type(value) is not bool:
            self.finding("error", f"{name} doit être un booléen JSON (true ou false).", name)
            return None
        return value

    def amount(self, payload, name, prefix=""):
        value = self.required(payload, name)
        if value is None:
            return None
        if not isinstance(value, str) or not MONEY.fullmatch(value):
            self.finding("error", f"{prefix + name} doit être un montant positif en texte, point décimal et 2 décimales maximum. Les avoirs ne sont pas traités.", prefix + name)
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            self.finding("error", f"Montant invalide : {prefix + name}.", prefix + name)
            return None

    def date(self, payload, name, required=True, prefix=""):
        value = self.required(payload, name) if required else payload.get(name)
        if value is None or value == "":
            return None
        try:
            if not isinstance(value, str) or not DATE.fullmatch(value):
                raise ValueError()
            return date.fromisoformat(value)
        except ValueError:
            self.finding("error", f"Date invalide : {prefix + name} (format AAAA-MM-JJ).", prefix + name)
            return None

    def currency(self, payload, prefix=""):
        value = self.required(payload, "currency")
        if value is None:
            return None
        if not isinstance(value, str) or value not in CURRENCIES:
            self.finding("error", "Devise non prise en charge. Utilisez EUR, USD, GBP, CHF, CAD ou AUD (2 décimales).", prefix + "currency")
            return None
        return value

    def blocked(self):
        return bool(self.value["missing_fields"]) or any(f["severity"] == "error" for f in self.value["findings"])


def _document_scope(payload, result):
    """Immutable source warnings cannot disappear when the dossier is edited.

The document service derives these markers from preserved extraction text.
They indicate that this simple workflow is insufficient, not a legal finding.
"""
    if "_document_source" not in payload:
        return
    source = payload["_document_source"]
    flags = source.get("document_risk_flags") if isinstance(source, dict) else None
    field = "_document_source.document_risk_flags"
    if not isinstance(flags, list) or len(flags) > 20:
        result.finding("error", "Les contrôles de périmètre de la pièce source sont absents ou invalides. Reprendre la revue documentaire avant validation.", field)
        result.check("document_scope", False, "Les marqueurs documentaires conservés doivent être disponibles.")
        return
    seen = set()
    for flag in flags:
        valid = (isinstance(flag, dict) and isinstance(flag.get("code"), str) and flag["code"] in DOCUMENT_RISK_MESSAGES
                 and type(flag.get("page")) is int and 1 <= flag["page"] <= 5
                 and isinstance(flag.get("quote"), str) and bool(flag["quote"].strip()))
        if not valid:
            result.finding("error", "Un marqueur de la pièce source n'est pas pris en charge. Faire contrôler le document avant validation.", field)
            continue
        code = flag["code"]
        if code not in seen:
            result.finding("error", DOCUMENT_RISK_MESSAGES[code] + f" Signal conservé sur la page {flag['page']}.", field)
            seen.add(code)
    result.check("document_scope", not flags,
                 "Aucun marqueur bloquant détecté dans le texte extrait ; vérifier la pièce originale." if not flags else
                 "La pièce comporte un marqueur qui exige une revue au-delà du contrôle simple.")


def invoice(task, today, receivable=False):
    result = CheckResult()
    payload = task["payload"]
    for field in ("invoice_number", "supplier", "customer"):
        result.text(payload, field)
    issued = result.date(payload, "issue_date")
    due = result.date(payload, "due_date")
    amounts = {field: result.amount(payload, field) for field in ("net_amount", "vat_rate", "vat_amount", "total_amount")}
    currency = result.currency(payload)
    paid = result.boolean(payload, "paid")
    disputed = result.boolean(payload, "disputed") if receivable else False
    _document_scope(payload, result)
    partial_fields = {"paid_amount", "amount_paid", "credit_amount", "remaining_amount", "has_partial_payment", "partial_payment"}
    connector_source = payload.get("_connector_source")
    imported = connector_source.get("imported_values", {}) if isinstance(connector_source, dict) else {}
    imported_partial = isinstance(imported, dict) and bool(partial_fields.intersection(imported))
    partial_description = any(phrase in task["description"].casefold() for phrase in ("acompte", "paiement partiel", "partial payment", "pago parcial"))
    if partial_fields.intersection(payload) or imported_partial or receivable and partial_description:
        result.finding("error", "Les paiements partiels, acomptes, avoirs et soldes restants ne sont pas rapprochés automatiquement. Vérifier le solde manuellement avant de préparer une relance.", "paid_amount")
    if payload.get("bank_details_changed") is not None:
        bank_changed = result.boolean(payload, "bank_details_changed")
        if bank_changed is True:
            result.finding("error", "Coordonnées bancaires modifiées : faire vérifier le bénéficiaire et le RIB par un canal indépendant avant validation.", "bank_details_changed")
    last_reminder = result.date(payload, "last_reminder_date", required=False) if receivable else None
    rate = amounts["vat_rate"]
    if rate is not None and rate > 100:
        result.finding("error", "Le taux de TVA doit être compris entre 0 et 100. Son applicabilité doit être vérifiée séparément.", "vat_rate")
    if issued and due:
        valid = due >= issued
        result.check("date_order", valid, "L'échéance ne doit pas précéder la date de facture.")
        if not valid:
            result.finding("error", "L'échéance précède la date de facture.", "due_date")
    if issued and issued > today:
        result.finding("warning", "La facture est datée dans le futur : confirmer qu'il s'agit d'un brouillon.", "issue_date")
    if last_reminder and last_reminder > today:
        result.finding("error", "La date de dernière relance est dans le futur.", "last_reminder_date")
    if all(value is not None for value in amounts.values()) and rate <= 100:
        expected_vat = (amounts["net_amount"] * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        valid_vat = expected_vat == amounts["vat_amount"]
        result.check("vat_arithmetic", valid_vat, f"Calcul global à un taux, arrondi au centime : TVA attendue {expected_vat}.")
        if not valid_vat:
            result.finding("error", f"TVA différente du calcul global ({expected_vat}). Faire vérifier l'arrondi par ligne ou les taux multiples avant validation.", "vat_amount")
        expected_total = amounts["net_amount"] + amounts["vat_amount"]
        valid_total = expected_total == amounts["total_amount"]
        result.check("total_arithmetic", valid_total, f"HT + TVA = {expected_total.quantize(CENT)}.")
        if not valid_total:
            result.finding("error", f"Le total TTC ne correspond pas à HT + TVA ({expected_total.quantize(CENT)}).", "total_amount")
    result.finding("info", "Contrôle arithmétique d'une facture simple à un taux. Aucune validation fiscale, des mentions légales, de l'identité du bénéficiaire ou du paiement.")
    if receivable:
        zero_balance = amounts["total_amount"] is not None and amounts["total_amount"] == 0
        if zero_balance:
            result.finding("info", "Le montant TTC est nul : aucune demande de règlement à préparer.", "total_amount")
        if disputed is True:
            result.finding("error", "Facture contestée : traiter le litige manuellement avant toute relance.", "disputed")
        if paid is True:
            result.finding("info", "Facture déclarée réglée : aucune relance à préparer.", "paid")
        if due and due >= today:
            result.finding("info", "L'échéance n'est pas dépassée : aucune relance à préparer.", "due_date")
        if due and due < today and paid is False:
            result.finding("warning", f"Échéance dépassée de {(today - due).days} jour(s), selon les informations saisies.", "due_date")
        if last_reminder == today:
            result.finding("warning", "Une relance est déjà enregistrée aujourd'hui. Éviter un doublon.", "last_reminder_date")
        if not result.blocked() and not zero_balance and paid is False and due and due < today and last_reminder != today:
            result.value["draft"] = (
                f"BROUILLON À RELIRE — aucun envoi\n\nObjet : Suivi de la facture {payload['invoice_number']}\n\n"
                f"Bonjour,\n\nSauf erreur de notre part, la facture {payload['invoice_number']} d'un montant de "
                f"{amounts['total_amount'].quantize(CENT)} {currency}, arrivée à échéance le {due.isoformat()}, "
                "reste en attente de règlement dans notre suivi. Pourriez-vous nous confirmer son statut ? "
                "Si le règlement a déjà été effectué, merci de nous l'indiquer afin de mettre notre suivi à jour.\n\n"
                "Merci pour votre retour.\n[Signature à compléter]"
            )
        result.value["summary"] = "Relance bloquée : informations à corriger ou litige à traiter." if result.blocked() else (
            "Brouillon de relance prêt pour relecture humaine." if result.value["draft"] else "Aucune relance proposée pour cette facture.")
    else:
        result.value["summary"] = "Facture à corriger ou compléter avant relecture." if result.blocked() else "Contrôles arithmétiques terminés. Relecture humaine requise."
        if not result.blocked():
            result.value["draft"] = f"Note de contrôle interne — facture {payload['invoice_number']} : calculs cohérents sur les montants saisis. Vérifier la pièce originale, les mentions obligatoires, le taux applicable et les coordonnées de paiement. Aucun règlement exécuté."
    return result.value


def bookkeeping(task, today):
    result = CheckResult()
    payload = task["payload"]
    period = result.text(payload, "period")
    if period:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}", period):
                raise ValueError()
            date.fromisoformat(period + "-01")
        except ValueError:
            result.finding("error", "Période invalide : utilisez AAAA-MM.", "period")
    documents = result.required(payload, "documents")
    if not isinstance(documents, list) or not documents or len(documents) > 300:
        result.finding("error", "Fournir entre 1 et 300 pièces structurées. Aucun justificatif réel n'est importé par cette liste.", "documents")
        documents = []
    expected = payload.get("expected_documents")
    if expected is not None:
        if type(expected) is not int or not 0 <= expected <= 10000:
            result.finding("error", "expected_documents doit être un entier de 0 à 10 000.", "expected_documents")
        elif expected > len(documents):
            result.finding("error", f"{expected - len(documents)} pièce(s) attendue(s) manquante(s).", "expected_documents")
        elif expected < len(documents):
            result.finding("warning", "Le nombre de pièces dépasse le nombre attendu : vérifier le périmètre.", "expected_documents")
    else:
        result.finding("warning", "Le nombre de pièces attendu n'est pas fourni : l'exhaustivité du dossier ne peut pas être vérifiée.", "expected_documents")
    ids, fingerprints, totals = set(), set(), {}
    for index, document in enumerate(documents):
        prefix = f"documents[{index}]."
        if not isinstance(document, dict):
            result.finding("error", "Chaque pièce doit être un objet JSON.", prefix.rstrip("."))
            continue
        child = CheckResult()
        fields = {field: child.text(document, field) for field in ("id", "type", "number")}
        doc_date = child.date(document, "date")
        amount = child.amount(document, "total_amount")
        currency = child.currency(document)
        for finding in child.value["findings"]:
            if finding.get("field"):
                finding["field"] = prefix + finding["field"]
            result.value["findings"].append(finding)
        result.value["missing_fields"].extend(prefix + field for field in child.value["missing_fields"])
        doc_id = fields["id"]
        if doc_id:
            if doc_id in ids:
                result.finding("error", f"Identifiant de pièce dupliqué : {doc_id}.", prefix + "id")
            ids.add(doc_id)
        if doc_date and period and doc_date.strftime("%Y-%m") != period:
            result.finding("warning", "Pièce datée hors de la période sélectionnée : rattachement à vérifier.", prefix + "date")
        if doc_date and doc_date > today:
            result.finding("warning", "Pièce datée dans le futur.", prefix + "date")
        if not child.blocked():
            fingerprint = (fields["type"].casefold(), fields["number"].casefold(), doc_date.isoformat(), str(amount.normalize()), currency)
            if fingerprint in fingerprints:
                result.finding("error", "Doublon potentiel (type, numéro, date, montant et devise identiques) : vérifier les originaux.", prefix)
            fingerprints.add(fingerprint)
            totals[currency] = totals.get(currency, Decimal("0")) + amount
    result.check("document_validation", not result.blocked(), "Contrôle des métadonnées, doublons potentiels et nombre de pièces attendu.")
    result.value["summary"] = "Dossier à compléter ou corriger." if result.blocked() else "Index de pièces préparé pour relecture et transmission manuelle."
    if not result.blocked():
        amount_summary = "; ".join(f"{value.quantize(CENT)} {key}" for key, value in sorted(totals.items()))
        result.value["draft"] = f"Dossier de précomptabilité — {period}\n{len(documents)} pièce(s) déclarée(s).\nSomme brute des montants saisis par devise : {amount_summary}.\nCes sommes ne constituent ni un solde comptable, ni une TVA déductible, ni une trésorerie. Rapprocher chaque ligne de son justificatif et faire valider par le comptable."
    result.finding("info", "Aucune écriture comptable, déclaration ou transmission n'a été effectuée.")
    return result.value


def expense_duplicates(task, other_tasks):
    """Potential repeated receipt across claimants; no finding of fraud or payment."""
    def fingerprint(value):
        if value.get("skill_id") != "expense-review":
            return None
        payload = value.get("payload", {})
        merchant, when, amount, currency = (payload.get(key) for key in ("merchant", "expense_date", "total_amount", "currency"))
        if not all(isinstance(item, str) and item.strip() for item in (merchant, when, amount, currency)):
            return None
        if not MONEY.fullmatch(amount) or not DATE.fullmatch(when) or currency not in CURRENCIES:
            return None
        try:
            date.fromisoformat(when)
            canonical_merchant = " ".join(unicodedata.normalize("NFKC", merchant).casefold().split())
            return canonical_merchant, when, str(Decimal(amount).normalize()), currency
        except (ValueError, InvalidOperation):
            return None
    own = fingerprint(task)
    if own is None:
        return []
    return sorted({other["id"] for other in other_tasks if isinstance(other, dict) and isinstance(other.get("id"), str)
                   and other["id"] != task.get("id") and fingerprint(other) == own})


def expense(task, today, duplicate_ids=None):
    """One original receipt, its business context and explicit human attestations."""
    result = CheckResult()
    payload = task["payload"]
    for field in ("merchant", "employee_ref", "business_purpose", "policy_ref"):
        result.text(payload, field)
    when = result.date(payload, "expense_date")
    total = result.amount(payload, "total_amount")
    currency = result.currency(payload)
    for field, choices in (("category", {"travel", "meals", "lodging", "office", "other"}),
                           ("payment_method", {"employee_card", "company_card", "cash", "bank_transfer", "other"})):
        value = result.text(payload, field)
        if value is not None and value not in choices:
            result.finding("error", "Valeur non prise en charge : " + field + ".", field)
    states = {field: result.boolean(payload, field) for field in ("paid_by_company", "reimbursed", "business_only", "policy_confirmed", "payment_confirmed")}
    if total is not None and total <= 0:
        result.finding("error", "Le total du reçu doit être strictement positif ; aucun montant à préparer sur une dépense nulle.", "total_amount")
    if when and when > today:
        result.finding("error", "La date de dépense est future : vérifier le justificatif.", "expense_date")
    for field, blocked_value, message in (
        ("paid_by_company", True, "Dépense déclarée payée par l'entreprise : ne pas préparer un remboursement au demandeur."),
        ("reimbursed", True, "Dépense déclarée déjà remboursée : vérifier le suivi pour éviter un double traitement."),
        ("business_only", False, "Dépense personnelle ou mixte : une ventilation vérifiée est nécessaire hors de ce contrôle simple."),
        ("policy_confirmed", False, "La politique interne applicable n'est pas confirmée ; décision du responsable nécessaire."),
        ("payment_confirmed", False, "Le paiement de la dépense n'est pas confirmé ; un reçu seul ne suffit pas à le prouver."),
    ):
        if states[field] is blocked_value:
            result.finding("error", message, field)
    if payload.get("payment_method") == "company_card" and states["paid_by_company"] is False:
        result.finding("error", "Carte entreprise et paiement déclaré hors entreprise se contredisent.", "payment_method")
    if "policy_limit" in payload:
        limit = result.amount(payload, "policy_limit")
        policy_currency = result.text(payload, "policy_currency")
        if policy_currency != currency:
            result.finding("error", "Le plafond doit être exprimé dans la devise du reçu ; aucune conversion automatique.", "policy_currency")
        elif total is not None and limit is not None:
            within = total <= limit
            result.check("expense_policy_limit", within, "Comparaison avec le plafond fourni dans la même devise.")
            if not within:
                result.finding("error", "Le total dépasse le plafond déclaré ; décision du responsable nécessaire.", "policy_limit")
    else:
        result.finding("warning", "Aucun plafond chiffré fourni : aucun respect d'un plafond n'est attesté.", "policy_limit")
        if "policy_currency" in payload:
            result.finding("error", "Une devise de plafond sans montant ne définit pas une limite exploitable.", "policy_limit")
    source = payload.get("_document_source")
    receipt_valid = (isinstance(source, dict) and source.get("human_verified") is True and
                     isinstance(source.get("document_id"), str) and bool(source["document_id"]) and
                     isinstance(source.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is not None and
                     type(source.get("extraction_version")) is int and source["extraction_version"] > 0 and
                     isinstance(source.get("fields"), dict))
    if receipt_valid:
        evidence_fields = source["fields"]
        if "receipt_reviews" in source:
            reviews = source["receipt_reviews"]
            if (not isinstance(reviews, list) or not reviews or not isinstance(reviews[-1], dict)
                    or reviews[-1].get("human_verified") is not True or not isinstance(reviews[-1].get("fields"), dict)):
                receipt_valid = False
            else:
                evidence_fields = reviews[-1]["fields"]
        for field in ("merchant", "expense_date", "total_amount", "currency"):
            evidence = evidence_fields.get(field)
            if not isinstance(evidence, dict) or evidence.get("reviewed_value") != payload.get(field):
                receipt_valid = False
    result.check("expense_receipt", bool(receipt_valid), "Original conservé et champs du reçu explicitement vérifiés ; aucune authenticité fiscale certifiée.")
    if not receipt_valid:
        result.finding("error", "Importer le reçu par Documents puis confirmer marchand, date, total et devise. Les champs modifiés doivent être revus sur l'original.", "_document_source")
    if {"paid_amount", "remaining_amount", "amount_paid", "credit_amount", "partial_payment", "has_partial_payment"}.intersection(payload):
        result.finding("error", "Un paiement partiel, un solde ou un avoir est déclaré : rapprocher la dépense hors de ce contrôle simple.", "paid_amount")
    flags = source.get("document_risk_flags") if isinstance(source, dict) else None
    if not isinstance(flags, list):
        result.finding("error", "Les marqueurs de la pièce source sont absents ; revue documentaire requise.", "_document_source.document_risk_flags")
    else:
        for flag in flags:
            code = flag.get("code") if isinstance(flag, dict) else None
            if code in ("multiple_tax_rates", "special_vat"):
                result.finding("info", "TVA particulière ou plusieurs taux observés : la revue porte seulement sur le total brut, sans TVA déductible calculée.", "vat_amount")
            else:
                result.finding("error", "La pièce comporte un marqueur nécessitant une revue spécialisée : " + (code if isinstance(code, str) else "inconnu") + ".", "_document_source.document_risk_flags")
    if duplicate_ids is None or not isinstance(duplicate_ids, list) or any(not isinstance(item, str) for item in duplicate_ids):
        result.finding("error", "Le contrôle courant des doublons n'a pas été exécuté.", "expense_duplicates")
        result.check("expense_duplicates", False, "Comparer aux dossiers actuels de cette instance.")
    elif duplicate_ids:
        result.finding("error", "Doublon possible de marchand, date, total et devise : rapprocher les dossiers " + ", ".join(duplicate_ids[:10]) + ".", "expense_duplicates")
        result.check("expense_duplicates", False, "Même reçu possible, y compris avec un autre demandeur ; aucune fraude présumée.")
    else:
        result.check("expense_duplicates", True, "Aucun dossier de mêmes marchand, date, total et devise dans l'instance au moment du contrôle.")
    if "vat_amount" in payload:
        vat = result.amount(payload, "vat_amount")
        if vat is not None and total is not None and vat > total:
            result.finding("error", "Le montant de TVA observé dépasse le total ; contrôler le reçu.", "vat_amount")
    result.finding("info", "Aucune TVA déductible, règle fiscale, indemnité kilométrique, conversion ou somme à rembourser n'est calculée. Aucun paiement exécuté.")
    result.value["summary"] = "Note de frais bloquée : justificatif ou décision à compléter." if result.blocked() else "Reçu et contexte préparés pour la décision humaine, sans remboursement automatique."
    if not result.blocked():
        result.value["draft"] = (f"NOTE INTERNE — {payload['employee_ref']}\nMarchand : {payload['merchant']}\nDate : {when.isoformat()}\n"
                                 f"Total brut observé : {total.quantize(CENT)} {currency}\nMotif : {payload['business_purpose']}\n"
                                 f"Politique déclarée : {payload['policy_ref']}\nDécision du responsable requise. Aucun remboursement ni traitement fiscal exécuté.")
    return result.value


def triage(task, today):
    result = CheckResult()
    context = task["description"].strip()
    request_text = task["payload"].get("text")
    if request_text is not None and (not isinstance(request_text, str) or len(request_text) > 12000):
        result.finding("error", "Le texte de la demande doit être un texte de 12 000 caractères maximum.", "text")
        request_text = ""
    request_text = (request_text or "").strip()
    text = "\n\n".join(dict.fromkeys(part for part in (request_text, context) if part))
    if not text:
        result.missing("description")
    rules = [
        ("receivables-followup", ["impay", "relance", "retard", "unpaid", "overdue", "impago", "cobro"]),
        ("invoice-check", ["facture", "invoice", "factura", "tva", "iva"]),
        ("bookkeeping-pack", ["comptab", "justificatif", "receipt", "contabil", "pièce"]),
        ("hr-onboarding", ["salari", "embauch", "contrat de travail", "employee", "empleado", "nómina"]),
        ("contract-watch", ["contrat", "contract", "contrato", "résili", "renouvel"]),
        ("deadline-watch", ["échéanc", "deadline", "date limite", "vencimiento", "plazo"]),
        ("expense-review", ["note de frais", "expense", "frais de déplacement", "gastos", "kilométr"]),
        ("supplier-watch", ["fournisseur", "supplier", "proveedor", "bon de commande"]),
        ("compliance-watch", ["conformité", "compliance", "rgpd", "gdpr", "verifactu", "facturation électronique"]),
        ("cash-visibility", ["trésorerie", "cash flow", "cashflow", "tesorería", "liquidité"]),
        ("weekly-brief", ["bilan hebdomadaire", "synthèse hebdomadaire", "weekly", "resumen semanal"]),
    ]
    lower = text.casefold()
    matches = [skill_id for skill_id, words in rules if any(word in lower for word in words)]
    result.check("description_available", bool(text), "Le tri se base sur le texte de la demande et le contexte saisis.")
    if text:
        destinations = ", ".join(matches) or "qualification manuelle"
        result.value["summary"] = f"Orientation indicative : {destinations}."
        result.value["draft"] = f"Fiche de tri interne\nOrientation proposée : {destinations}.\nÀ confirmer : objet de la demande, pièce source, échéance, responsable et prochaine action.\nAucune tâche externe créée et aucun message envoyé."
        result.finding("warning", "Orientation par mots-clés, sans compréhension IA. Confirmer la catégorie et le caractère urgent avec la pièce source.")
        if any(phrase in lower for phrase in ("nouveau rib", "changement de rib", "changement iban", "nouvel iban", "bank details changed", "new bank account", "nuevo iban", "cambio de cuenta", "fraude")):
            result.finding("error", "Changement bancaire ou risque de fraude évoqué : vérification indépendante obligatoire par le responsable. Aucune donnée bancaire modifiée.", "description")
            result.value["summary"] = "Demande sensible : vérification humaine indépendante obligatoire."
    else:
        result.value["summary"] = "Description nécessaire pour orienter la demande."
    return result.value


def guided(task, today):
    result = CheckResult()
    skill = get_skill(task["skill_id"])
    result.value["summary"] = f"{skill['name']} : cadrage guidé, sans analyse spécialisée automatisée."
    result.finding("error", "Cette compétence fournit un guide de préparation. Son contrôle spécialisé n'est pas implémenté et exige une vérification humaine externe.", "specialist_review")
    result.value["missing_fields"] = ["specialist_review"]
    if not task["description"].strip():
        result.missing("description")
    names = []
    for value in skill.get("inputs", []):
        names.append(value if isinstance(value, str) else str(value.get("name", value.get("id", "Pièce source"))))
    result.value["draft"] = "Fiche de préparation interne\n" + "\n".join(f"□ Réunir : {name}" for name in names)
    result.value["draft"] += "\n□ Confirmer le pays, l'entreprise concernée, l'échéance et le responsable.\n□ Faire contrôler les sources et la conclusion par la personne compétente.\nAucune formalité, écriture, action RH ou transmission réalisée."
    result.check("specialist_automation", False, "Compétence guidée uniquement ; aucune validation automatique.")
    return result.value


def analyze(task, today=None, expense_duplicate_ids=None):
    today = today or date.today()
    skill_id = task["skill_id"]
    if skill_id == "invoice-check":
        result = invoice(task, today)
    elif skill_id == "receivables-followup":
        result = invoice(task, today, receivable=True)
    elif skill_id == "bookkeeping-pack":
        result = bookkeeping(task, today)
    elif skill_id == "admin-triage":
        result = triage(task, today)
    elif skill_id == "expense-review":
        result = expense(task, today, expense_duplicate_ids)
    else:
        result = guided(task, today)
    result["context"] = context_manifest(task)
    result["analyzed_on"] = today.isoformat()
    result["outbound_executed"] = False
    return result


def result_status(result):
    return "blocked" if result["missing_fields"] or any(row["severity"] == "error" for row in result["findings"]) else "needs_review"
