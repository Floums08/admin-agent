"""Independent synthetic invoice and bank cases for the downloadable demo pack.

Only specimen data and separately authored expectations live here. No rendering,
network, import, payment or customer communication takes place. ``notes`` are
ordinary fictitious document content; test instructions belong in ``expected``.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import io


def _day(as_of: date, offset: int) -> str:
    if type(as_of) is not date:
        raise ValueError("as_of doit être une date, sans heure.")
    try:
        return (as_of + timedelta(days=offset)).isoformat()
    except OverflowError:
        raise ValueError("La date ne permet pas de générer toutes les échéances relatives.") from None


def _payload(as_of: date, case_id: str, country: str, net: str, rate: str,
             *, due_offset: int = 15, issue_offset: int = -30) -> dict:
    net_amount = Decimal(net)
    vat_amount = (net_amount * Decimal(rate) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if country == "FR":
        supplier, customer = "Fournisseur fictif FR-A", f"Client fictif {case_id}"
    else:
        supplier, customer = "Proveedor ficticio ES-A", f"Cliente ficticio {case_id}"
    return {
        "invoice_number": f"DEMO-{country}-{case_id}",
        "supplier": supplier,
        "customer": customer,
        "issue_date": _day(as_of, issue_offset),
        "due_date": _day(as_of, due_offset),
        "net_amount": format(net_amount, ".2f"),
        "vat_rate": format(Decimal(rate), ".2f"),
        "vat_amount": format(vat_amount, ".2f"),
        "total_amount": format(net_amount + vat_amount, ".2f"),
        "currency": "EUR",
        # A separate fictional operator assertion; never extract this from OCR.
        "paid": False,
    }


def _finance(as_of: date, case_id: str, *, direction: str = "receivable",
             disputed: bool = False) -> dict:
    return {
        "direction": direction,
        "opening_paid_amount": "0.00",
        "opening_as_of": _day(as_of, -7),
        "evidence_ref": f"PREUVE-FICTIVE-OUVERTURE-{case_id}",
        "disputed": disputed,
    }


def invoice_cases(as_of: date) -> list[dict]:
    """Return ten fresh cases: eight PDF files (one exact copy) and two PNGs.

    F10 must be copied byte-for-byte from the rendered F01 file. Its different
    packaging title and ID must never be rendered into that duplicate document.
    Payment/dispute context and financial scenarios are kept outside the invoice.
    """
    _day(as_of, 0)
    specifications = [
        ("F01", "Facture client — deux règlements de 400 puis 800 EUR", "FR", "pdf", "1000.00", "20.00", 10),
        ("F02", "Facture fournisseur espagnole — décaissement de 242 EUR", "ES", "pdf", "200.00", "21.00", 7),
        ("F03", "Facture client future — simulation d'affacturage", "FR", "pdf", "2000.00", "20.00", 30),
        ("F04", "Facture client échue — solde restant de 360 EUR", "FR", "pdf", "300.00", "20.00", -12),
        ("F05", "Facture espagnole — litige déclaré dans le suivi", "ES", "pdf", "500.00", "21.00", 20),
        ("F06", "Facture au total TTC incohérent", "FR", "pdf", "600.00", "20.00", 15),
        ("F07", "Facture dont l'échéance précède l'émission", "FR", "pdf", "450.00", "20.00", -20),
        ("F08", "Facture française en image — montant de 1 210 EUR", "FR", "png", "1008.33", "20.00", 12),
        ("F09", "Facture espagnole en image — même montant de 1 210 EUR", "ES", "png", "1000.00", "21.00", 18),
    ]
    explanations = {
        "F01": "Après relecture puis validation interne, ouvrir un solde de 1 200 EUR en fin de J-7. Les deux affectations bancaires successives de 400 puis 800 EUR donnent partiel puis payé ; le dossier source reste inchangé.",
        "F02": "Contrôles arithmétiques cohérents. Le suivi est fournisseur/payable : seul le débit de 242 EUR peut solder cette facture après confirmation humaine.",
        "F03": "Créance de 2 400 EUR entièrement impayée, non litigieuse et à échéance J+30. La simulation financière reste indicative ; une avance du factor ne doit pas être affectée comme paiement client.",
        "F04": "Contrôles arithmétiques cohérents. Au jour de référence, le suivi indique douze jours de retard et 360 EUR restants. Le mouvement de sens opposé fourni dans le CSV doit être refusé.",
        "F05": "L'analyse de facture simple reste cohérente. Le litige est une déclaration distincte dans le registre financier : aucune suggestion automatique ni simulation d'affacturage ; un éventuel paiement réel demanderait une preuve et une affectation manuelle.",
        "F06": "Conserver le TTC imprimé de 725 EUR dans les champs relus. HT 600 + TVA 120 = 720 EUR : le contrôle total_arithmetic doit échouer. Ne pas corriger le total intentionnellement faux pour faire passer le test.",
        "F07": "L'émission est J-10 et l'échéance J-20. Le contrôle date_order doit bloquer le dossier ; ne pas inverser les dates au moment de relire la pièce.",
        "F08": "Image française nominale : 1 008,33 EUR HT + 201,67 EUR de TVA = 1 210 EUR. Le virement sans référence de même montant ne suffit pas à choisir entre F08 et F09.",
        "F09": "Image espagnole nominale : 1 000 EUR HT + 210 EUR d'IVA = 1 210 EUR. Même montant et même sens que F08 : l'encaissement non référencé reste à rapprocher manuellement.",
    }
    cases = []
    for case_id, title, country, format_name, net, rate, due_offset in specifications:
        payload = _payload(as_of, case_id, country, net, rate, due_offset=due_offset,
                           issue_offset=-10 if case_id == "F07" else -30)
        if case_id == "F06":
            payload["total_amount"] = "725.00"
        failed_checks = ["total_arithmetic"] if case_id == "F06" else ["date_order"] if case_id == "F07" else []
        case = {
            "id": case_id,
            "title": title,
            "kind": "invoice",
            "country": country,
            "language": "fra" if country == "FR" else "spa",
            "format": format_name,
            "payload": payload,
            "notes": ["Prestation fictive de préparation documentaire."] if country == "FR" else ["Servicio ficticio de preparación documental."],
            "expected": {
                "analysis_status": "blocked" if failed_checks else "needs_review",
                "check_ids": failed_checks,
                "explanation": explanations[case_id],
            },
        }
        if not failed_checks:
            case["finance"] = _finance(as_of, case_id, direction="payable" if case_id == "F02" else "receivable", disputed=case_id == "F05")
        cases.append(case)

    duplicate = deepcopy(cases[0])
    duplicate.update(id="F10", title="Copie strictement identique de F01 — déduplication documentaire", duplicate_of="F01")
    duplicate.pop("finance")  # Never register a second receivable for the copied original.
    duplicate["expected"] = {
        "analysis_status": "needs_review",
        "check_ids": [],
        "document_dedup": True,
        "explanation": "Le fichier doit être une copie binaire exacte de F01. Son second import doit retrouver le même original, sans créer une seconde facture financière. Si l'on compare uniquement les champs, ils sont identiques à F01.",
    }
    cases.append(duplicate)
    return cases


def bank_cases(as_of: date) -> dict:
    """Return a strict CSV and a separate, runtime-ID-free financial answer key.

    Transactions are dated after the closing opening balance (J-7), never in the
    future. Test positive allocations first in the order stated. The amount-only
    ambiguity remains reproducible after F01 is settled because F08 and F09 are
    independently open for the same EUR amount.
    """
    cases = {case["id"]: case for case in invoice_cases(as_of)}
    reference = {key: item["payload"]["invoice_number"] for key, item in cases.items()}
    rows = [
        ("TX-DEMO-001", _day(as_of, -6), "400.00", "EUR", f"Reglement fictif {reference['F01']}"),
        ("TX-DEMO-002", _day(as_of, -3), "800.00", "EUR", f"Reglement fictif {reference['F01']}"),
        ("TX-DEMO-003", _day(as_of, -5), "-242.00", "EUR", f"Pago ficticio {reference['F02']}"),
        ("TX-DEMO-004", _day(as_of, -2), "1210.00", "EUR", "Encaissement fictif sans reference de facture"),
        ("TX-DEMO-005", _day(as_of, -2), "1210.00", "USD", f"Reglement fictif {reference['F08']}"),
        ("TX-DEMO-006", _day(as_of, -1), "-360.00", "EUR", f"Reglement fictif {reference['F04']}"),
        ("TX-DEMO-007", _day(as_of, -1), "1920.00", "EUR", f"Avance factor {reference['F03']}"),
        ("TX-DEMO-008", _day(as_of, -1), "605.00", "EUR", f"Reglement fictif {reference['F05']}"),
    ]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("transaction_id", "date", "amount", "currency", "reference"))
    writer.writerows(rows)
    return {
        "account_ref": "DEMO-COMPTE-FICTIF-01",
        "csv_text": stream.getvalue(),
        "expected_scenarios": [
            {
                "id": "B01", "invoice_case_ids": ["F01"], "transaction_ids": ["TX-DEMO-001", "TX-DEMO-002"],
                "expected": {"allocation_steps": [
                    {"transaction_id": "TX-DEMO-001", "amount": "400.00", "payment_status": "partial", "paid_amount": "400.00", "remaining_amount": "800.00"},
                    {"transaction_id": "TX-DEMO-002", "amount": "800.00", "payment_status": "paid", "paid_amount": "1200.00", "remaining_amount": "0.00"},
                ]},
                "explanation": "Relire les versions courantes entre les deux confirmations. Aucun paiement n'est exécuté ; seules les affectations internes évoluent.",
            },
            {
                "id": "B02", "invoice_case_ids": ["F02"], "transaction_ids": ["TX-DEMO-003"],
                "expected": {"allocation_steps": [{"transaction_id": "TX-DEMO-003", "amount": "242.00", "payment_status": "paid", "paid_amount": "242.00", "remaining_amount": "0.00"}]},
                "explanation": "Le mouvement bancaire est négatif, mais le montant d'affectation est toujours positif. La facture est de type payable.",
            },
            {
                "id": "B03", "invoice_case_ids": ["F08", "F09"], "transaction_ids": ["TX-DEMO-004"],
                "expected": {"suggestion_count": 0, "manual_only_reason": "amount_only", "candidate_invoice_cases": ["F08", "F09"], "allocated_amount": "0.00"},
                "explanation": "Un montant identique sans référence ne permet pas d'attribuer l'encaissement à l'une des deux factures. Laisser la ligne non affectée pendant cet exercice.",
            },
            {
                "id": "B04", "invoice_case_ids": ["F08"], "transaction_ids": ["TX-DEMO-005"],
                "expected": {"allocation_error_code": "currency_mismatch", "allocated_amount": "0.00"},
                "explanation": "La facture est en EUR et l'opération en USD : aucun taux de conversion ne doit être inventé.",
            },
            {
                "id": "B05", "invoice_case_ids": ["F04"], "transaction_ids": ["TX-DEMO-006"],
                "expected": {"allocation_error_code": "direction_mismatch", "remaining_amount": "360.00", "overdue": True, "days_overdue": 12},
                "explanation": "Une sortie bancaire ne solde pas une facture client. Le retard reste visible.",
            },
            {
                "id": "B06", "invoice_case_ids": ["F03"], "transaction_ids": ["TX-DEMO-007"],
                "expected": {"allocation_error_code": "financing_not_payment", "paid_amount": "0.00", "remaining_amount": "2400.00"},
                "explanation": "Une avance du factor constitue un financement, pas un règlement du débiteur. Ne pas affecter cette ligne à la facture client.",
            },
            {
                "id": "B07", "invoice_case_ids": ["F05"], "transaction_ids": ["TX-DEMO-008"],
                "expected": {"disputed": True, "suggestion_count": 0, "factoring_error_code": "factoring_blocked", "allocated_amount": "0.00"},
                "explanation": "Le litige déclaré supprime les suggestions et bloque la simulation. Le relevé seul ne résout pas le litige. Une affectation manuelle reste techniquement possible avec une preuve appropriée, mais n'est pas demandée dans ce scénario.",
            },
            {
                "id": "B08", "invoice_case_ids": [], "transaction_ids": [row[0] for row in rows],
                "expected": {"first_import_created": 8, "repeat_import_created": 0, "repeat_import_duplicates": 8},
                "explanation": "Relire l'aperçu avant import. Réimporter le même fichier et le même compte ne doit pas dupliquer les transactions.",
            },
            {
                "id": "B09", "invoice_case_ids": ["F03"], "transaction_ids": [],
                "expected": {"nominal": "2400.00", "advance": "1920.00", "reserve": "480.00", "fees": "29.00", "interest": "9.60", "total_cost": "38.60", "net_cash": "1881.40", "days": 30, "paid_amount": "0.00"},
                "explanation": "Conditions fictives saisies : avance 80 %, commission 1 % du nominal, frais fixes 5 EUR, intérêt annuel simple 6 % sur l'avance pendant 30 jours, base 360. La réserve de 480 EUR n'est pas un coût et reste indisponible ; aucune offre de financement n'est présumée.",
            },
        ],
        "simulate_inputs": {
            "invoice_case_id": "F03",
            "advance_rate": "80.00",
            "fee_rate": "1.00",
            "annual_interest_rate": "6.00",
            "fixed_fee": "5.00",
            "funding_date": _day(as_of, 0),
            "day_basis": 360,
        },
    }
