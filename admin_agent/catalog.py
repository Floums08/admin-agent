"""Select one skill, with a bounded, attributable context budget."""

import hashlib
import json
from pathlib import Path

from .errors import AppError


ROOT = Path(__file__).resolve().parent.parent
MAX_SKILL_BYTES = 18_000
MAX_PAYLOAD_BYTES = 32_000
CORE_IDS = {"invoice-check", "receivables-followup", "bookkeeping-pack", "admin-triage", "expense-review"}
FALLBACK = [
    ("invoice-check", "Contrôle de facture"),
    ("receivables-followup", "Préparation des relances clients"),
    ("bookkeeping-pack", "Dossier de précomptabilité"),
    ("admin-triage", "Tri administratif"),
    ("expense-review", "Notes de frais"),
    ("deadline-watch", "Échéances"),
    ("supplier-watch", "Suivi fournisseurs"),
    ("contract-watch", "Suivi contractuel"),
    ("hr-onboarding", "Préparation RH"),
    ("compliance-watch", "Veille de conformité"),
    ("cash-visibility", "Visibilité de trésorerie"),
    ("weekly-brief", "Synthèse hebdomadaire"),
]


def skills(include_body=True):
    source = ROOT / "data" / "skills.json"
    if source.exists():
        try:
            rows = json.loads(source.read_text(encoding="utf-8"))["skills"]
            if not isinstance(rows, list):
                raise ValueError("Invalid catalog")
        except (ValueError, KeyError, OSError) as exc:
            raise AppError("Le catalogue de compétences est indisponible.", 503, "catalog_unavailable") from exc
    else:
        rows = [dict(id=key, name=name, description=name, priority="P0" if key in CORE_IDS else "P1",
                     agent="Assistant administratif", inputs=[], outputs=[],
                     status="implemented" if key in CORE_IDS else "guided", path=f"skills/{key}/SKILL.md")
                for key, name in FALLBACK]
    output = []
    for row in rows:
        item = {k: row.get(k, [] if k in ("inputs", "outputs") else "")
                for k in ("id", "name", "description", "priority", "agent", "inputs", "outputs", "status", "path")}
        if include_body:
            item["body"] = skill_body(item)[0]
        output.append(item)
    return output


def get_skill(skill_id):
    for row in skills(include_body=False):
        if row["id"] == skill_id:
            return row
    raise AppError("Compétence inconnue.", 400, "unknown_skill")


def skill_body(skill):
    candidate = (ROOT / skill.get("path", "")).resolve()
    try:
        candidate.relative_to(ROOT / "skills")
    except ValueError:
        return "", False
    if not candidate.is_file():
        return "", False
    with candidate.open("rb") as source:
        raw = source.read(MAX_SKILL_BYTES + 1)
    return raw[:MAX_SKILL_BYTES].decode("utf-8", errors="ignore"), len(raw) > MAX_SKILL_BYTES


def context_manifest(task):
    skill = get_skill(task["skill_id"])
    body, truncated = skill_body(skill)
    payload = json.dumps(task["payload"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "strategy": "selected_skill_and_current_task_only",
        "skill_id": skill["id"],
        "sources": [{"path": skill["path"], "sha256": hashlib.sha256(body.encode()).hexdigest(),
                     "bytes": len(body.encode()), "available": bool(body)}],
        "skill_truncated": truncated,
        "payload_bytes": len(payload),
        "estimated_tokens": (len(body.encode()) + len(payload) + len(task["description"].encode()) + 3) // 4,
        "token_estimate_method": "UTF-8 bytes / 4 (approximation, not billing)",
        "other_tasks_included": False,
        "provider_called": False,
    }
