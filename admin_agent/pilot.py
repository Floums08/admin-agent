"""Private, offline invoice-pilot observations; never a deployment approval.

The registry records human judgments, not invoice values. Synthetic rehearsals and
authorized client observations require separate directories. Aggregate reports do
not include case identifiers, reviewer aliases, evidence locations, or notes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


SCHEMA_VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_REVISIONS = 1000
STATE_NAME = "pilot.json"
CRITICAL_FIELDS = (
    "invoice_number", "supplier", "customer", "issue_date", "due_date",
    "net_amount", "vat_rate", "vat_amount", "total_amount", "currency",
)
CASE_STATUSES = {"not_tested", "pass", "fail", "out_of_scope"}
EXTRACTIONS = {"not_tested", "correct", "incorrect", "missing", "correct_abstention"}
REVIEWS = {"not_tested", "confirmed", "corrected", "unresolved"}
OUTCOMES = {"not_tested", "blocked", "needs_review", "ready"}
BLOCKERS = {
    "unresolved_critical_field", "document_unreadable", "scope_unsupported",
    "field_mismatch", "missing_evidence", "workflow_failure", "security_issue", "other",
}
TIMES = ("baseline_seconds", "assisted_seconds", "review_seconds", "correction_seconds")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")


class PilotError(ValueError):
    """A controlled refusal containing no input values or private paths."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_bytes(value):
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (UnicodeError, TypeError, ValueError, RecursionError):
        raise PilotError("Données JSON invalides.") from None


def _parse(raw):
    def unique(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise PilotError("Clé JSON dupliquée.")
            output[key] = value
        return output

    def reject_constant(value):
        raise PilotError("Nombre JSON non fini refusé.")

    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise PilotError("Fichier JSON invalide ou illisible.") from None
    if not isinstance(result, dict):
        raise PilotError("Un objet JSON est attendu.")
    return result


def _text(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise PilotError("Texte obligatoire absent ou trop long.")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise PilotError("Caractère de contrôle refusé.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise PilotError("Texte Unicode invalide.") from None
    return value.strip()


def _enum(value, choices, name):
    if not isinstance(value, str) or value not in choices:
        raise PilotError(f"Valeur invalide pour {name}.")
    return value


def _token(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise PilotError("Identifiant invalide : utiliser un alias de 1 à 80 caractères, sans donnée personnelle.")
    return value


def _safe_path(value, *, outside_repo=True):
    path = Path(value).expanduser().absolute()
    if ".." in path.parts:
        raise PilotError("Les chemins contenant '..' sont refusés.")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PilotError("Les liens symboliques sont refusés pour les données du pilote.")
    path = path.resolve()
    if outside_repo:
        application_root = Path(__file__).resolve().parents[1]
        if path == application_root or application_root in path.parents:
            raise PilotError("Le registre et ses observations doivent rester hors du dépôt de code.")
        for part in (path, *path.parents):
            marker = part / ".git"
            if marker.is_file() or (marker / "HEAD").is_file():
                raise PilotError("Les données du pilote sont interdites dans un dépôt Git, même ignorées.")
    return path


def _check_permissions(info, directory=False):
    if directory and not stat.S_ISDIR(info.st_mode) or not directory and not stat.S_ISREG(info.st_mode):
        raise PilotError("Un répertoire privé ou fichier ordinaire est requis.")
    if not directory and info.st_nlink != 1:
        raise PilotError("Les fichiers possédant plusieurs liens sont refusés.")
    if os.name == "posix":
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise PilotError("Permissions trop larges : utiliser 0700 pour le répertoire et 0600 pour les fichiers privés.")
        if info.st_uid != os.getuid():
            raise PilotError("Le répertoire et ses fichiers doivent appartenir à l'utilisateur courant.")


def _directory(value):
    path = _safe_path(value)
    try:
        _check_permissions(path.stat(), directory=True)
    except OSError:
        raise PilotError("Répertoire privé de pilote absent ou inaccessible.") from None
    return path


def _read(path, *, private=True):
    path = _safe_path(path, outside_repo=private)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise PilotError("Fichier non ordinaire ou supérieur à 2 Mio.")
        if private:
            _check_permissions(info)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise PilotError("Le fichier dépasse 2 Mio.")
        return _parse(raw)
    except OSError:
        raise PilotError("Fichier inaccessible.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _sync_directory(directory):
    if os.name == "posix":
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write(path, raw, *, replace=False):
    """Same-directory staged write, fsync, then atomic rename under a registry lock."""
    path = _safe_path(path)
    parent = _directory(path.parent)
    if len(raw) > MAX_BYTES:
        raise PilotError("Le registre dépasse la limite de 2 Mio.")
    if path.exists():
        if not replace:
            raise PilotError("Le fichier existe déjà ; aucun écrasement autorisé.")
        _check_permissions(path.stat())
    descriptor, staged_name = tempfile.mkstemp(prefix=".pilot-", suffix=".tmp", dir=parent)
    staged = Path(staged_name)
    try:
        os.chmod(staged, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(staged, path)
        else:
            # Hard-link publication is exclusive and atomic; unlink staging immediately.
            try:
                os.link(staged, path)
            except FileExistsError:
                raise PilotError("Le fichier existe déjà ; aucun écrasement autorisé.") from None
            staged.unlink()
        _sync_directory(parent)
    except OSError:
        raise PilotError("Écriture privée impossible ; la version précédente est conservée.") from None
    finally:
        staged.unlink(missing_ok=True)


@contextmanager
def _lock(directory):
    """OS-backed lock: released automatically if the process exits or crashes."""
    lock_path = _safe_path(directory / ".pilot.lock")
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError:
        raise PilotError("Verrou du registre inaccessible.") from None
    try:
        _check_permissions(os.fstat(descriptor))
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PilotError("Le registre est utilisé par une autre commande ; réessayer après sa fin.") from None
        elif os.name == "nt":
            import msvcrt
            os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise PilotError("Le registre est utilisé par une autre commande.") from None
        else:
            raise PilotError("Verrouillage privé non pris en charge sur ce système.")
        yield
    finally:
        os.close(descriptor)


def _empty_fields():
    return {field: {"extraction": "not_tested", "review": "not_tested"} for field in CRITICAL_FIELDS}


def _case(case_id, country, expected_scope, expected_result=None):
    _token(case_id)
    _enum(country, {"FR", "ES"}, "country")
    _enum(expected_scope, {"in_scope", "out_of_scope"}, "expected_scope")
    if expected_result is not None:
        _enum(expected_result, {"blocked", "needs_review"}, "expected_result")
    return dict(case_id=case_id, country=country, expected_scope=expected_scope, expected_result=expected_result,
                version=0, status="not_tested", observed_result="not_tested", reviewer_ref="", evidence_ref="",
                critical_fields=_empty_fields(), timing={}, blockers=[], note="", recorded_at=None)


def init_pilot(directory, cohort, *, case_count=None, country=None, manifest=None):
    _enum(cohort, {"synthetic", "client"}, "cohort")
    if case_count is not None and (type(case_count) is not int or not 10 <= case_count <= 30):
        raise PilotError("Le lot doit contenir entre 10 et 30 factures.")
    if manifest is not None:
        metadata = _read(manifest, private=cohort == "client")
        if metadata.get("schema_version") != 1 or not isinstance(metadata.get("cases"), list):
            raise PilotError("Le manifeste doit utiliser schema_version=1 et contenir une liste cases.")
        if metadata.get("synthetic") is not (cohort == "synthetic"):
            raise PilotError("Le manifeste doit indiquer explicitement synthetic et correspondre à la cohorte.")
        rows = metadata["cases"]
        if not 10 <= len(rows) <= 30 or case_count is not None and case_count != len(rows):
            raise PilotError("Le manifeste doit contenir entre 10 et 30 cas, conformément au nombre demandé.")
        cases = []
        for row in rows:
            if not isinstance(row, dict):
                raise PilotError("Chaque cas du manifeste doit être un objet.")
            cases.append(_case(row.get("case_id"), row.get("country"), row.get("expected_scope"), row.get("expected_status")))
    else:
        _enum(country, {"FR", "ES"}, "country")
        cases = [_case(f"case-{index:03d}", country, "in_scope") for index in range(1, (case_count or 10) + 1)]
    if len({case["case_id"] for case in cases}) != len(cases):
        raise PilotError("Le manifeste contient des identifiants de cas dupliqués.")
    path = _safe_path(directory)
    if path.exists():
        raise PilotError("Choisir un nouveau répertoire hors Git ; le répertoire existe déjà.")
    if not path.parent.is_dir():
        raise PilotError("Créer d'abord le répertoire parent privé ou utiliser un répertoire parent existant.")
    state = dict(schema_version=SCHEMA_VERSION, cohort=cohort, created_at=_now(), updated_at=_now(), revision=0,
                 critical_fields=list(CRITICAL_FIELDS), cases=cases, history=[])
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        _write(path / STATE_NAME, _json_bytes(state))
    except OSError:
        raise PilotError("Initialisation privée impossible.") from None
    return {"created": True, "cohort": cohort, "case_count": len(cases), "status": "not_tested", "deployment_readiness": "not_assessed"}


def _load(directory):
    directory = _directory(directory)
    state = _read(directory / STATE_NAME)
    if (state.get("schema_version") != SCHEMA_VERSION or state.get("cohort") not in ("synthetic", "client")
            or type(state.get("revision")) is not int or not 0 <= state["revision"] <= MAX_REVISIONS
            or state.get("critical_fields") != list(CRITICAL_FIELDS)
            or not isinstance(state.get("cases"), list) or not 10 <= len(state["cases"]) <= 30
            or not isinstance(state.get("history"), list) or len(state["history"]) != state["revision"]):
        raise PilotError("Structure ou version du registre invalide.")
    ids = set()
    for case in state["cases"]:
        if not isinstance(case, dict):
            raise PilotError("Cas invalide dans le registre.")
        if not {"case_id", "country", "expected_scope", "expected_result", "version", "status", "observed_result", "reviewer_ref", "evidence_ref", "critical_fields", "timing", "blockers", "note", "recorded_at"}.issubset(case):
            raise PilotError("Champs obligatoires du registre absents.")
        _case(case.get("case_id"), case.get("country"), case.get("expected_scope"), case.get("expected_result"))
        if case["case_id"] in ids:
            raise PilotError("Cas dupliqué dans le registre.")
        ids.add(case["case_id"])
        if type(case.get("version")) is not int or not 0 <= case["version"] <= state["revision"]:
            raise PilotError("Version de cas invalide.")
        # Revalidate on read; editing the private JSON cannot silently inflate metrics.
        _observation(case, {key: case[key] for key in (
            "case_id", "version", "status", "observed_result", "reviewer_ref", "evidence_ref", "critical_fields", "timing", "blockers", "note")})
    return state


def _seconds(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,5}(?:\.\d{1,2})?", value):
        raise PilotError("Les temps sont des secondes réellement mesurées, en entier ou texte décimal à deux décimales maximum.")
    amount = Decimal(value)
    if amount > 86400:
        raise PilotError("Un temps de traitement ne peut pas dépasser 86 400 secondes.")
    return format(amount.quantize(Decimal("0.01")), "f")


def _observation(case, data):
    allowed = {"case_id", "version", "status", "observed_result", "reviewer_ref", "evidence_ref", "critical_fields", "timing", "blockers", "note"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise PilotError("L'observation contient des champs non pris en charge ; ne pas y copier les valeurs d'une facture.")
    if data.get("case_id") != case["case_id"]:
        raise PilotError("L'observation ne correspond pas au cas sélectionné.")
    if type(data.get("version")) is not int or data["version"] != case["version"]:
        raise PilotError("La version du cas a changé ; générer un nouveau modèle avant de modifier.")
    status = _enum(data.get("status"), CASE_STATUSES, "status")
    outcome = _enum(data.get("observed_result", "not_tested"), OUTCOMES, "observed_result")
    reviewer = _text(data.get("reviewer_ref", ""), 80, required=status != "not_tested")
    if reviewer:
        _token(reviewer)
    evidence = _text(data.get("evidence_ref", ""), 500, required=status != "not_tested")
    note = _text(data.get("note", ""), 2000)
    fields = _empty_fields()
    supplied = data.get("critical_fields", {})
    if not isinstance(supplied, dict) or set(supplied) - set(CRITICAL_FIELDS):
        raise PilotError("Liste de champs critiques invalide.")
    for name, value in supplied.items():
        if not isinstance(value, dict) or set(value) != {"extraction", "review"}:
            raise PilotError("Chaque champ critique attend uniquement extraction et review.")
        extraction = _enum(value["extraction"], EXTRACTIONS, "extraction")
        review = _enum(value["review"], REVIEWS, "review")
        if review == "confirmed" and extraction not in {"correct", "correct_abstention"}:
            raise PilotError("Seule une valeur correcte ou une abstention correcte peut être confirmée.")
        if review == "corrected" and extraction not in {"incorrect", "missing"}:
            raise PilotError("Une correction exige une erreur ou un champ manquant observé avant correction.")
        if review != "not_tested" and extraction == "not_tested":
            raise PilotError("Un champ non évalué ne peut pas être déclaré relu.")
        fields[name] = {"extraction": extraction, "review": review}
    blockers = data.get("blockers", [])
    if not isinstance(blockers, list) or len(blockers) > len(BLOCKERS) or any(not isinstance(x, str) or x not in BLOCKERS for x in blockers) or len(set(blockers)) != len(blockers):
        raise PilotError("La liste des blocages doit utiliser les codes documentés, sans doublon.")
    timing = data.get("timing", {})
    if not isinstance(timing, dict) or set(timing) - set(TIMES) - {"measurement", "paired_comparison"}:
        raise PilotError("Structure des mesures de temps invalide.")
    normalized_timing = {}
    if timing:
        if timing.get("measurement") != "observed":
            raise PilotError("Les estimations ne sont pas acceptées : enregistrer uniquement des temps observés.")
        if type(timing.get("paired_comparison", False)) is not bool:
            raise PilotError("paired_comparison doit être un booléen JSON.")
        normalized_timing = {"measurement": "observed", "paired_comparison": timing.get("paired_comparison", False)}
        for name in TIMES:
            if name in timing:
                normalized_timing[name] = _seconds(timing[name])
        if not any(name in normalized_timing for name in TIMES):
            raise PilotError("Aucun temps observé n'a été fourni.")
        if normalized_timing["paired_comparison"] and not {"baseline_seconds", "assisted_seconds"}.issubset(normalized_timing):
            raise PilotError("Une comparaison exige deux temps observés sur le même cas, avec le même périmètre et en secondes.")
        for component, total in (("review_seconds", "assisted_seconds"), ("correction_seconds", "review_seconds"), ("correction_seconds", "assisted_seconds")):
            if component in normalized_timing and total in normalized_timing and Decimal(normalized_timing[component]) > Decimal(normalized_timing[total]):
                raise PilotError("Les temps doivent respecter correction ≤ revue ≤ traitement assisté (inclusions, pas sommes).")
    if status == "not_tested" and (outcome != "not_tested" or timing or blockers or any(value != {"extraction": "not_tested", "review": "not_tested"} for value in fields.values())):
        raise PilotError("Un cas non testé ne peut pas contenir de résultat, temps, revue ou blocage observé.")
    if status == "pass":
        if case["expected_scope"] == "out_of_scope":
            raise PilotError("Un scénario hors périmètre doit utiliser le statut out_of_scope, avec preuve du refus.")
        if outcome == "not_tested" or case["expected_result"] is not None and outcome != case["expected_result"]:
            raise PilotError("Le résultat observé doit correspondre au résultat attendu du scénario.")
        if blockers or any(value["review"] not in {"confirmed", "corrected"} for value in fields.values()):
            raise PilotError("Un scénario pass exige la revue résolue des dix champs critiques et aucun blocage du test.")
    if status == "fail" and not blockers:
        raise PilotError("Un scénario fail exige au moins un code de blocage.")
    if status == "out_of_scope" and not note:
        raise PilotError("Préciser en note privée pourquoi le document est hors périmètre.")
    if status == "out_of_scope" and outcome != "blocked":
        raise PilotError("Un cas hors périmètre exige un blocage observé ; si le système l'a accepté, enregistrer fail.")
    return dict(status=status, observed_result=outcome, reviewer_ref=reviewer, evidence_ref=evidence,
                critical_fields=fields, timing=normalized_timing, blockers=blockers, note=note)


def record_observation(directory, data):
    directory = _directory(directory)
    with _lock(directory):
        state = _load(directory)
        if state["revision"] >= MAX_REVISIONS:
            raise PilotError("La limite de 1 000 révisions est atteinte ; conserver ce registre et ouvrir un nouveau pilote.")
        if not isinstance(data, dict):
            raise PilotError("Un objet JSON d'observation est attendu.")
        case = next((item for item in state["cases"] if item["case_id"] == data.get("case_id")), None)
        if case is None:
            raise PilotError("Cas absent du registre ; le lot et la cohorte sont immuables.")
        observed = _observation(case, data)
        timestamp = _now()
        case.update(observed, version=case["version"] + 1, recorded_at=timestamp)
        state["revision"] += 1
        state["updated_at"] = timestamp
        state["history"].append({"revision": state["revision"], "case_id": case["case_id"], "case_version": case["version"],
                                 "status": case["status"], "recorded_at": timestamp,
                                 "observation_sha256": hashlib.sha256(_json_bytes(observed)).hexdigest()})
        _write(directory / STATE_NAME, _json_bytes(state), replace=True)
    return {"recorded": True, "case_version": case["version"], "registry_revision": state["revision"], "status": case["status"], "outbound_executed": False}


def observation_template(directory, case_id):
    state = _load(directory)
    case = next((item for item in state["cases"] if item["case_id"] == case_id), None)
    if case is None:
        raise PilotError("Cas absent du registre.")
    return {key: case[key] for key in ("case_id", "version", "status", "observed_result", "reviewer_ref", "evidence_ref", "critical_fields", "timing", "blockers", "note")}


def _decimal(value):
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _percent(numerator, denominator):
    return _decimal(Decimal(numerator) * 100 / Decimal(denominator)) if denominator else None


def report(directory):
    state = _load(directory)
    cases = state["cases"]
    counts = Counter(case["status"] for case in cases)
    # Out-of-scope controls do not inflate field accuracy or time savings.
    eligible = [case for case in cases if case["expected_scope"] == "in_scope" and case["status"] != "out_of_scope"]
    extraction, reviews = Counter(), Counter()
    for case in eligible:
        for value in case["critical_fields"].values():
            extraction[value["extraction"]] += 1
            reviews[value["review"]] += 1
    evaluated_values = sum(extraction[key] for key in ("correct", "incorrect", "missing"))
    expected_fields = len(eligible) * len(CRITICAL_FIELDS)
    supplied_blockers = Counter(blocker for case in cases for blocker in case["blockers"])
    measured = [case for case in eligible if case["status"] in {"pass", "fail"}]
    timing = {}
    for name in TIMES:
        values = [Decimal(case["timing"][name]) for case in measured if name in case["timing"]]
        timing[name] = {"measured_cases": len(values), "total": _decimal(sum(values, Decimal(0))) if values else None,
                        "mean": _decimal(sum(values, Decimal(0)) / len(values)) if values else None}
    pairs = [case for case in measured if case["timing"].get("paired_comparison") is True]
    baseline = sum((Decimal(case["timing"]["baseline_seconds"]) for case in pairs), Decimal(0))
    assisted = sum((Decimal(case["timing"]["assisted_seconds"]) for case in pairs), Decimal(0))
    mismatches = sum((case["expected_scope"] == "out_of_scope" and case["status"] not in {"not_tested", "out_of_scope"})
                     or (case["expected_scope"] == "in_scope" and case["status"] == "out_of_scope") for case in cases)
    pending = []
    if state["cohort"] == "synthetic":
        pending.append("synthetic_rehearsal_is_not_client_validation")
    if counts["not_tested"]:
        pending.append("untested_cases")
    if counts["fail"]:
        pending.append("failed_cases")
    if mismatches:
        pending.append("scope_mismatches")
    if reviews["unresolved"]:
        pending.append("unresolved_critical_fields")
    if not pairs:
        pending.append("no_observed_paired_time_comparison")
    return {
        "schema_version": 1, "cohort": state["cohort"], "registry_revision": state["revision"],
        "evidence_basis": "human_recorded_observations_not_independently_verified",
        "deployment_readiness": "not_assessed", "outbound_executed": False,
        "redaction": "aggregate_only_no_case_ids_reviewer_refs_evidence_refs_notes_or_invoice_values",
        "cases": {"total": len(cases), "expected_in_scope": sum(case["expected_scope"] == "in_scope" for case in cases),
                  **{key: counts[key] for key in sorted(CASE_STATUSES)}, "scope_mismatches": mismatches},
        "extraction": {"eligible_critical_fields": expected_fields, "evaluated_values": evaluated_values,
                       **{key: extraction[key] for key in sorted(EXTRACTIONS)},
                       "value_accuracy_percent": _percent(extraction["correct"], evaluated_values),
                       "evaluation_coverage_percent": _percent(evaluated_values + extraction["correct_abstention"], expected_fields),
                       "correct_abstention_excluded_from_value_accuracy": True},
        "review": {**{key: reviews[key] for key in sorted(REVIEWS)},
                   "coverage_percent": _percent(expected_fields - reviews["not_tested"], expected_fields)},
        "timing": {"unit": "seconds", "basis": "observed_only", "assisted_includes_review_includes_correction": True,
                   "measurements": timing,
                   "paired_comparison": {"cases": len(pairs), "same_case_and_scope_attested_by_operator": True if pairs else None,
                                         "baseline_total": _decimal(baseline) if pairs else None,
                                         "assisted_total": _decimal(assisted) if pairs else None,
                                         "saved_seconds": _decimal(baseline - assisted) if pairs else None,
                                         "saved_percent": _percent(baseline - assisted, baseline) if pairs else None}},
        "recorded_blockers": {key: supplied_blockers[key] for key in sorted(BLOCKERS) if supplied_blockers[key]},
        "pending_evaluation": pending,
        "limitations": ["small_sample_no_population_estimate", "latest_observation_per_case_only", "manual_claims_not_independent_certification",
                        "operational_security_and_client_acceptance_require_separate_evidence", "private_local_files_not_encrypted_by_this_tool"],
    }


def report_csv(value):
    """Only controlled metric names and numeric/enumerated values enter CSV."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["metric", "value"])
    def walk(prefix, item):
        if isinstance(item, dict):
            for key in sorted(item):
                walk(f"{prefix}.{key}" if prefix else key, item[key])
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(f"{prefix}.{index}", child)
        else:
            writer.writerow([prefix, "" if item is None else str(item).lower() if type(item) is bool else item])
    walk("", value)
    return stream.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Registre privé de pilote factures : observations humaines, aucune action externe.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Créer un lot privé de 10 à 30 cas, hors de tout dépôt Git.")
    init.add_argument("--directory", required=True)
    init.add_argument("--cohort", required=True, choices=("synthetic", "client"))
    init.add_argument("--cases", type=int, dest="case_count")
    init.add_argument("--country", choices=("FR", "ES"))
    init.add_argument("--manifest")
    template = sub.add_parser("template", help="Créer un modèle d'observation privé, sans écraser de fichier.")
    template.add_argument("--directory", required=True)
    template.add_argument("--case", required=True, dest="case_id")
    template.add_argument("--output", required=True)
    record = sub.add_parser("record", help="Enregistrer une observation humaine avec vérification de version.")
    record.add_argument("--directory", required=True)
    record.add_argument("--record", required=True)
    summary = sub.add_parser("report", help="Rapport agrégé sans références privées ni valeurs de factures.")
    summary.add_argument("--directory", required=True)
    summary.add_argument("--format", choices=("json", "csv"), default="json")
    summary.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init_pilot(args.directory, args.cohort, case_count=args.case_count, country=args.country, manifest=args.manifest)
        elif args.command == "template":
            result = observation_template(args.directory, args.case_id)
            _write(args.output, _json_bytes(result))
            result = {"created": True, "private_template": True, "observations_in_stdout": False}
        elif args.command == "record":
            result = record_observation(args.directory, _read(args.record))
        else:
            result = report(args.directory)
            raw = _json_bytes(result) if args.format == "json" else report_csv(result).encode("utf-8")
            if args.output:
                _write(args.output, raw)
                result = {"created": True, "aggregate_report": True, "format": args.format, "deployment_readiness": "not_assessed"}
            else:
                sys.stdout.write(raw.decode("utf-8"))
                return 0
        sys.stdout.write(_json_bytes(result).decode("utf-8"))
        return 0
    except (PilotError, OSError):
        # Neither paths, arbitrary values nor evidence references are printed on failure.
        exc = sys.exc_info()[1]
        message = str(exc) if isinstance(exc, PilotError) else "Opération locale impossible ; vérifier le chemin et les permissions privés."
        sys.stderr.write(f"Pilote refusé : {message}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
