"""Synthetic expense receipts and their separate human review expectations.

Only merchant, expense_date, total_amount, currency, optional vat_amount and
``notes`` belong on the rendered receipt. The remaining payload fields describe
the fictitious human review, not facts inferred from OCR. No server provenance
is fabricated here: import each original through Documents and confirm fields.

``expected.check_ids`` lists checks expected to fail, not every executed check.
Some blocking findings (company payment, prior reimbursement) have no failed
check of their own. Expectations assume originals have been reviewed and the
current duplicate check has run. E01 is analysed before E08; after E08 exists,
both must be blocked by the duplicate check. These cases measure neither real
OCR accuracy nor customer time savings.
"""

from datetime import date, timedelta


def expense_cases(as_of: date) -> list[dict]:
    """Return eight independent, deterministic cases dated before ``as_of``.

    E02 and E06 are PNG receipts; the other six are PDFs. E07 intentionally has
    no expense_date anywhere in the receipt payload. Every name, employee
    reference and policy is fictitious. Caller mutations cannot affect a later
    call, or another case's nested data.
    """
    if type(as_of) is not date:
        raise TypeError("as_of must be a datetime.date, without a time component")
    if as_of.toordinal() <= 8:
        raise ValueError("as_of must allow eight preceding calendar days")

    def reviewed_payload(merchant, days_ago, total, employee, purpose, category, **extra):
        payload = {
            "merchant": merchant,
            "expense_date": (as_of - timedelta(days=days_ago)).isoformat(),
            "total_amount": total,
            "currency": "EUR",
            "employee_ref": employee,
            "business_purpose": purpose,
            "category": category,
            "payment_method": "employee_card",
            "policy_ref": "POL-DEMO-FRAIS-01 — politique fictive",
            "payment_confirmed": True,
            "paid_by_company": False,
            "reimbursed": False,
            "business_only": True,
            "policy_confirmed": True,
        }
        payload.update(extra)
        return payload

    def case(case_id, title, payload, notes, status="needs_review", checks=(),
             explanation="", country="FR", image_format="pdf", **extra):
        return {
            "id": case_id,
            "title": title,
            "kind": "expense",
            "country": country,
            "language": "spa" if country == "ES" else "fra",
            "format": image_format,
            "payload": payload,
            "notes": list(notes),
            "expected": {
                "analysis_status": status,
                "check_ids": list(checks),
                "explanation": explanation,
            },
            **extra,
        }

    meal = reviewed_payload(
        "Restaurant Démo des Tilleuls", 8, "42.00", "EMP-DEMO-01",
        "Repas pendant un déplacement professionnel fictif.", "meals",
        vat_amount="3.82", policy_limit="50.00", policy_currency="EUR",
    )
    undated = reviewed_payload(
        "Parking Démo des Peupliers", 2, "18.00", "EMP-DEMO-07",
        "Stationnement pendant une intervention professionnelle fictive.", "travel",
        policy_limit="30.00", policy_currency="EUR",
    )
    del undated["expense_date"]
    duplicate_meal = dict(meal, employee_ref="EMP-DEMO-08")

    return [
        case(
            "E01", "Repas professionnel — reçu français", meal,
            ["Menu déjeuner : 1", "Service de restauration sur place."],
            explanation=(
                "Avant la création de E08, le reçu et le contexte complets permettent "
                "une revue humaine (needs_review), sans remboursement automatique. "
                "Après création de E08, une nouvelle analyse de E01 doit être blocked "
                "avec expense_duplicates : les deux dossiers partagent marchand, "
                "date, total et devise malgré des demandeurs différents."
            ),
        ),
        case(
            "E02", "Taxi professionnel — ticket espagnol",
            reviewed_payload(
                "Taxi Demo del Olmo", 7, "27.50", "EMP-DEMO-02",
                "Trajet fictif entre la gare et un rendez-vous professionnel.", "travel",
                vat_amount="2.50", policy_limit="40.00", policy_currency="EUR",
            ),
            ["Servicio urbano de taxi.", "Trayecto: estación — recinto de reuniones."],
            country="ES", image_format="png",
            explanation=(
                "Les champs du ticket et les déclarations humaines sont complets ; "
                "le total reste sous le plafond fourni. Revue humaine requise, "
                "sans conclusion sur la déductibilité de l'IVA."
            ),
        ),
        case(
            "E03", "Hébergement professionnel — reçu français",
            reviewed_payload(
                "Hôtel Démo des Aulnes", 6, "132.00", "EMP-DEMO-03",
                "Une nuit pendant une mission professionnelle fictive.", "lodging",
                vat_amount="12.00", policy_limit="150.00", policy_currency="EUR",
            ),
            ["Hébergement : une nuit.", "Chambre individuelle."],
            explanation=(
                "Original et contexte complets, sans doublon ni dépassement du "
                "plafond déclaré : préparer la décision humaine sur le total brut."
            ),
        ),
        case(
            "E04", "Fournitures de bureau — reçu français",
            reviewed_payload(
                "Papeterie Démo des Érables", 5, "64.80", "EMP-DEMO-04",
                "Fournitures pour un atelier professionnel fictif.", "office",
                payment_method="company_card", paid_by_company=True,
                vat_amount="10.80", policy_limit="100.00", policy_currency="EUR",
            ),
            ["Cahiers, enveloppes et stylos.", "Lot de fournitures de bureau."],
            status="blocked",
            explanation=(
                "Le contexte humain déclare paid_by_company=true avec une carte "
                "entreprise : bloquer la préparation d'un remboursement au demandeur. "
                "Cette anomalie porte sur paid_by_company, sans contrôle nommé en échec."
            ),
        ),
        case(
            "E05", "Transport professionnel — reçu français",
            reviewed_payload(
                "Transport Démo des Saules", 4, "58.00", "EMP-DEMO-05",
                "Transport aller-retour pour une mission professionnelle fictive.", "travel",
                reimbursed=True, policy_limit="80.00", policy_currency="EUR",
            ),
            ["Titre de transport aller-retour.", "Classe standard."],
            status="blocked",
            explanation=(
                "Le suivi humain déclare reimbursed=true : bloquer un nouveau "
                "traitement et rapprocher le remboursement antérieur. Cette anomalie "
                "porte sur reimbursed, sans contrôle nommé en échec."
            ),
        ),
        case(
            "E06", "Repas professionnel — ticket numérisé",
            reviewed_payload(
                "Restaurant Démo des Châtaigniers", 3, "96.00", "EMP-DEMO-06",
                "Repas pendant une mission professionnelle fictive.", "meals",
                vat_amount="8.73", policy_limit="60.00", policy_currency="EUR",
            ),
            ["Menu dégustation : 1", "Service de restauration sur place."],
            image_format="png", status="blocked", checks=("expense_policy_limit",),
            explanation=(
                "Le total brut de 96,00 EUR dépasse le plafond interne fictif de "
                "60,00 EUR. Décision du responsable requise ; aucun plafond légal "
                "ni montant remboursable n'est déduit."
            ),
        ),
        case(
            "E07", "Stationnement — reçu sans date", undated,
            ["Stationnement couvert.", "Durée : quatre heures."],
            status="blocked", checks=("expense_receipt",),
            explanation=(
                "Aucune date n'apparaît sur la pièce : expense_date reste absent. "
                "Ne pas substituer la date d'import ou celle du scénario. Le dossier "
                "reste bloqué pour date manquante et preuve de reçu incomplète."
            ),
        ),
        case(
            "E08", "Repas professionnel — seconde édition du reçu", duplicate_meal,
            ["Menu déjeuner : 1", "Service de restauration sur place."],
            status="blocked", checks=("expense_duplicates",),
            explanation=(
                "Même marchand, date, total et devise que E01, autre demandeur et "
                "fichier visuellement distinct : doublon possible à rapprocher, "
                "sans présumer une fraude. E08 et toute nouvelle analyse de E01 "
                "doivent être bloqués par expense_duplicates."
            ),
            duplicate_of="E01", duplicate_kind="logical",
        ),
    ]
