"""Bounded, offline document extraction. Run in the isolated OCR worker only.

Documents are untrusted input. Extracted text and proposed values are evidence
for a person, never proof of payment, legal conformity or permission to act.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import warnings
import xml.etree.ElementTree as ET

MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_PAGES = 5
MAX_IMAGE_PIXELS = 20_000_000
MAX_EDGE = 2000
MAX_TEXT_BYTES = 64 * 1024
MAX_WORDS = 5000
MAX_OUTPUT_BYTES = 1024 * 1024
WALL_SECONDS = 60
LANGUAGES = ("eng", "fra", "spa", "fra+spa+eng")
MEDIA_TYPES = ("application/pdf", "image/png", "image/jpeg")
TOOLS = {name: Path("/usr/bin") / name for name in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract", "prlimit")}


class OCRError(Exception):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def detect_media(data: bytes) -> str:
    if not isinstance(data, bytes) or not data:
        raise OCRError("empty_document", "Le document est vide.", 400)
    if len(data) > MAX_INPUT_BYTES:
        raise OCRError("document_too_large", "Le fichier dépasse la limite de 5 Mio.", 413)
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise OCRError("unsupported_document", "Seuls les fichiers PDF, PNG et JPEG sont acceptés.", 415)


def _run(tool: str, args: list[str], directory: Path, deadline: float) -> bytes:
    """No shell, no inherited secrets, bounded disk output and process resources."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OCRError("ocr_timeout", "Le délai maximal d'extraction est dépassé.", 504)
    path = TOOLS[tool]
    if not path.is_file():
        raise OCRError("ocr_unavailable", "Un composant OCR requis n'est pas installé.", 503)
    command = [str(path), *args]
    if sys.platform.startswith("linux"):
        if not TOOLS["prlimit"].is_file():
            raise OCRError("ocr_unavailable", "Les limites de processus OCR sont indisponibles.", 503)
        # The worker's Docker cgroup caps the service at 64 PIDs. RLIMIT_NPROC
        # counts every thread sharing the host UID (including unrelated browsers).
        command = [str(TOOLS["prlimit"]), "--as=1073741824", "--cpu=55", "--fsize=33554432", "--nofile=64", "--", *command]
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "OMP_THREAD_LIMIT": "1", "TMPDIR": str(directory)}
    model_directory = os.environ.get("ADMIN_AGENT_OCR_TESSDATA_DIR")
    if tool == "tesseract" and model_directory:
        # Operator configuration only; never taken from a document or HTTP header.
        if not Path(model_directory).is_absolute() or not Path(model_directory).is_dir():
            raise OCRError("ocr_unavailable", "Le répertoire des langues OCR est indisponible.", 503)
        env["TESSDATA_PREFIX"] = model_directory
    output = directory / "command-output"
    try:
        with output.open("wb") as stream:
            result = subprocess.run(command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.DEVNULL, timeout=min(remaining, 30), check=False)
        if result.returncode:
            raise OCRError("document_unreadable", "Le document ne peut pas être extrait ; vérifier son format et sa protection.")
        if output.stat().st_size > 3 * 1024 * 1024:
            raise OCRError("extraction_too_large", "La sortie d'extraction dépasse la limite autorisée.")
        return output.read_bytes()
    except subprocess.TimeoutExpired:
        raise OCRError("ocr_timeout", "Le délai maximal d'extraction est dépassé.", 504) from None
    except OSError:
        raise OCRError("ocr_unavailable", "Le service d'extraction n'est pas disponible.", 503) from None


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeError:
        raise OCRError("invalid_extraction", "Le texte extrait n'est pas exploitable.") from None


def _box(x, y, right, bottom, width, height):
    values = [float(v) for v in (x, y, right, bottom, width, height)]
    if not all(math.isfinite(v) for v in values) or width <= 0 or height <= 0:
        raise OCRError("invalid_extraction", "Les coordonnées du document sont invalides.")
    return [round(max(0.0, min(1.0, v / scale)), 6) for v, scale in zip(values[:4], (width, height, width, height))]


def _line(text, words):
    if not words:
        return None
    return {"text": text, "bbox": [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
                                  max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]}


def _native_pages(data: bytes):
    try:
        root = ET.fromstring(data)
        pages = []
        for page in (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "page"):
            width, height = float(page.attrib["width"]), float(page.attrib["height"])
            if not all(math.isfinite(value) and 0 < value <= 20000 for value in (width, height)):
                raise ValueError("page dimensions")
            words, lines = [], []
            for line in (node for node in page.iter() if node.tag.rsplit("}", 1)[-1] == "line"):
                line_words = []
                for node in (node for node in line if node.tag.rsplit("}", 1)[-1] == "word"):
                    text = "".join(node.itertext()).strip()
                    if text:
                        word = {"text": text, "bbox": _box(float(node.attrib["xMin"]), float(node.attrib["yMin"]),
                                float(node.attrib["xMax"]), float(node.attrib["yMax"]), width, height), "confidence": None}
                        line_words.append(word)
                if line_words:
                    lines.append(_line(" ".join(w["text"] for w in line_words), line_words))
                    words.extend(line_words)
                    if len(words) > MAX_WORDS:
                        raise OCRError("extraction_too_large", "Le document contient trop de mots.")
            pages.append({"number": len(pages) + 1, "text": "\n".join(line["text"] for line in lines),
                          "method": "native", "width": width, "height": height, "words": words, "_lines": lines})
        return pages
    except (ET.ParseError, KeyError, ValueError, OverflowError):
        raise OCRError("invalid_extraction", "La structure du texte PDF n'est pas exploitable.") from None


def _prepare_image(source: Path, target: Path, expected_format=None):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise OCRError("ocr_unavailable", "Le composant image OCR n'est pas installé.", 503) from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as original:
                if expected_format and original.format != expected_format:
                    raise OCRError("media_mismatch", "Le format réel de l'image ne correspond pas au fichier.", 415)
                if original.width * original.height > MAX_IMAGE_PIXELS or max(original.size) > 20000:
                    raise OCRError("image_too_large", "L'image dépasse la limite de 20 millions de pixels.", 413)
                if getattr(original, "n_frames", 1) != 1:
                    raise OCRError("animated_image", "Les images contenant plusieurs vues ne sont pas acceptées.")
                original.load()
                normalized = ImageOps.exif_transpose(original).convert("RGB")
                resized = max(normalized.size) > MAX_EDGE
                normalized.thumbnail((MAX_EDGE, MAX_EDGE))
                normalized.save(target, format="PNG")
                return normalized.width, normalized.height, resized
    except OCRError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise OCRError("document_unreadable", "L'image est invalide ou trop volumineuse.") from None


def _ocr_page(source, number, language, directory, deadline, notes, expected_format=None):
    available = set(_decode(_run("tesseract", ["--list-langs"], directory, deadline)).splitlines()[1:])
    if not set(language.split("+")).issubset(available):
        raise OCRError("ocr_language_unavailable", "Une langue OCR demandée n'est pas installée.", 503)
    target = directory / "normalized.png"
    width, height, resized = _prepare_image(source, target, expected_format)
    if resized:
        notes.append(f"Page {number} : image réduite à 2 000 pixels maximum ; contrôler les petits caractères.")
    # Explicit output option also works with a minimal operator-provided model dir.
    raw = _run("tesseract", [str(target), "stdout", "-l", language, "--psm", "3", "-c", "tessedit_create_tsv=1"], directory, deadline)
    grouped, words = {}, []
    try:
        for row in csv.DictReader(io.StringIO(_decode(raw)), delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["level"] != "5" or not (row.get("text") or "").strip():
                continue
            x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            confidence = float(row["conf"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 100 or w < 0 or h < 0:
                raise ValueError("coordinates")
            word = {"text": row["text"].strip(), "bbox": _box(x, y, x + w, y + h, width, height), "confidence": round(confidence, 2)}
            words.append(word)
            grouped.setdefault((row["block_num"], row["par_num"], row["line_num"]), []).append(word)
            if len(words) > MAX_WORDS:
                raise OCRError("extraction_too_large", "Le document contient trop de mots.")
    except (ValueError, KeyError, TypeError, csv.Error):
        raise OCRError("invalid_extraction", "La sortie du moteur OCR n'est pas exploitable.") from None
    lines = [_line(" ".join(w["text"] for w in group), group) for group in grouped.values()]
    if any(word["confidence"] < 70 for word in words):
        notes.append(f"Page {number} : certains mots ont un score OCR inférieur à 70 ; vérification visuelle nécessaire.")
    if not words:
        notes.append(f"Page {number} : aucun texte détecté ; ne pas interpréter cette absence comme un document vide.")
    return {"number": number, "text": "\n".join(line["text"] for line in lines), "method": "ocr",
            "width": width, "height": height, "words": words, "_lines": lines}


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _amount(text, rate=False):
    if len(re.findall(r"\b(?:EUR|USD|GBP|CHF|CAD|AUD)\b|€", text, flags=re.I)) > 1:
        return None
    value = re.sub(r"\b(?:EUR|USD|GBP|CHF|CAD|AUD)\b|[€%]", "", text, flags=re.I).strip()
    value = value.replace("\u00a0", " ").replace("\u202f", " ")
    # Require a whole labelled value: do not grab one number out of a table row.
    if re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?", value):
        value = value.replace(" ", "")
    elif " " in value:
        return None
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d{2}", value):
        value = value.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", value):
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,10}(?:[.,]\d{1,2})?", value):
        value = value.replace(",", ".")
    else:
        return None
    try:
        number = Decimal(value)
        if number > (100 if rate else 9999999999):
            return None
        return format(number.quantize(Decimal("0.01")), "f")
    except InvalidOperation:
        return None


def _date(text):
    value = text.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        match = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", value)
        if match:
            first, second, year = map(int, match.groups())
            # 02/10 has no unambiguous meaning without a declared date convention.
            if first > 12 or first == second:
                return date(year, second, first).isoformat()
    except ValueError:
        pass
    return None


LABELS = {
    "merchant": r"(?:merchant|store|commercant|marchand|commerce|comercio|establecimiento)",
    "expense_date": r"(?:receipt date|purchase date|date d['’]achat|date du recu|fecha de compra|fecha del recibo|date|fecha)",
    "invoice_number": r"(?:invoice\s*(?:number|no\.?|#)|facture\s*(?:numero|n[o°º.]*)|factura\s*(?:numero|num\.?|n[o°º.]*))",
    "supplier": r"(?:supplier|fournisseur|proveedor|emetteur|emisor)",
    "customer": r"(?:customer|client|cliente|destinataire|destinatario)",
    "issue_date": r"(?:invoice date|issue date|date d['’]emission|date facture|fecha de emision|fecha factura)",
    "due_date": r"(?:due date|date d['’]echeance|echeance|fecha de vencimiento|vencimiento)",
    "net_amount": r"(?:total ht|montant ht|base imponible|subtotal|net amount|net total)",
    "vat_amount": r"(?:montant tva|total tva|importe iva|total iva|vat amount|vat total)",
    "vat_rate": r"(?:taux tva|taux de tva|tipo iva|tipo de iva|vat rate)",
    "total_amount": r"(?:total ttc|montant ttc|total facture|total factura|invoice total|grand total|total amount|total a payer|importe total|total pagado|total(?=\s*:\s*[0-9]|\s+[0-9]))",
    "currency": r"(?:currency|devise|moneda)",
}


def propose_candidates(pages):
    """Conservative labelled proposals with exact page quotations and zones."""
    proposals, notes, units = {}, [], set()
    for page in pages:
        for line in page.get("_lines", []):
            quote = line["text"]
            folded = _fold(quote)
            if len(folded) != len(quote):
                notes.append("Une ligne contient des caractères à normalisation ambiguë ; aucune valeur déduite de cette ligne.")
                continue
            for field, label in LABELS.items():
                match = re.fullmatch(r"\s*" + label + r"\s*(?::|\s)\s*(.+?)\s*", folded)
                if not match:
                    continue
                raw = quote[match.start(1):match.end(1)].strip()
                if field.endswith("_amount") or field == "currency":
                    units.update("EUR" if unit == "€" else unit.upper() for unit in re.findall(r"\b(?:EUR|USD|GBP|CHF|CAD|AUD)\b|€", raw, flags=re.I))
                value = raw
                if field.endswith("_amount") or field == "vat_rate":
                    value = _amount(raw, field == "vat_rate")
                elif field.endswith("_date"):
                    value = _date(raw)
                elif field == "currency":
                    value = raw.upper() if raw.upper() in ("EUR", "USD", "GBP", "CHF", "CAD", "AUD") else None
                elif field == "invoice_number":
                    value = raw if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,79}", raw) else None
                elif len(raw) > 200:
                    value = None
                if value is None:
                    notes.append(f"{field} : valeur étiquetée ambiguë ou non prise en charge ; saisir après contrôle.")
                    proposals.setdefault(field, []).append(None)
                else:
                    proposals.setdefault(field, []).append({"value": value, "page": page["number"], "quote": quote,
                                                         "bbox": line["bbox"], "method": page["method"]})
    candidates = {}
    for field, values in proposals.items():
        if any(value is None for value in values) or len({value["value"] for value in values if value}) != 1:
            notes.append(f"{field} : preuves multiples ou ambiguës ; aucune valeur sélectionnée.")
        else:
            candidates[field] = values[0]
    if len(units) > 1:
        for field in ("currency", "net_amount", "vat_amount", "total_amount"):
            candidates.pop(field, None)
        notes.append("Plusieurs devises sont indiquées ; les montants et la devise nécessitent une saisie vérifiée.")
    if any(re.search(r"\b(?:avoir|credit note|factura rectificativa|reverse charge|autoliquidation|inversion del sujeto pasivo)\b", _fold(page["text"])) for page in pages):
        notes.append("Document potentiellement particulier : avoir ou régime spécifique ; revue comptable requise.")
    return candidates, list(dict.fromkeys(notes))


def extract_document(data: bytes, media_type: str, language="fra+spa+eng", force_ocr=False):
    detected = detect_media(data)
    if media_type != detected:
        raise OCRError("media_mismatch", "Le type annoncé ne correspond pas au contenu du fichier.", 415)
    if language not in LANGUAGES or type(force_ocr) is not bool:
        raise OCRError("invalid_options", "Les options d'extraction sont invalides.", 400)
    deadline = time.monotonic() + WALL_SECONDS
    notes = ["Extraction indicative : contrôler les valeurs et les pages originales. Aucun état de paiement ou de litige n'est déduit."]
    with tempfile.TemporaryDirectory(prefix="admin-ocr-") as temp:
        directory = Path(temp)
        source = directory / ("input.pdf" if detected == "application/pdf" else "input.image")
        source.write_bytes(data)
        if detected == "application/pdf":
            info = _decode(_run("pdfinfo", [str(source)], directory, deadline))
            encrypted = re.search(r"^Encrypted:\s*(\w+)", info, re.M)
            if encrypted and encrypted.group(1).lower() != "no":
                raise OCRError("encrypted_pdf", "Les PDF chiffrés ou protégés ne sont pas acceptés.")
            count = re.search(r"^Pages:\s*(\d+)\s*$", info, re.M)
            if not count or not 1 <= int(count.group(1)) <= MAX_PAGES:
                raise OCRError("page_limit", "Un document doit contenir entre 1 et 5 pages.")
            pages = _native_pages(_run("pdftotext", ["-bbox-layout", "-enc", "UTF-8", str(source), "-"], directory, deadline))
            if len(pages) != int(count.group(1)):
                raise OCRError("invalid_extraction", "Le nombre de pages extraites est incohérent.")
            notes.append("Un PDF peut contenir une couche texte incomplète ou différente du visuel. Utiliser l'OCR forcé pour comparer en cas de doute.")
            for index, page in enumerate(pages):
                if force_ocr or len(re.sub(r"\s", "", page["text"])) < 80:
                    prefix = directory / "rendered"
                    _run("pdftoppm", ["-f", str(index + 1), "-l", str(index + 1), "-singlefile", "-scale-to", str(MAX_EDGE), "-png", str(source), str(prefix)], directory, deadline)
                    pages[index] = _ocr_page(directory / "rendered.png", index + 1, language, directory, deadline, notes, "PNG")
        else:
            pages = [_ocr_page(source, 1, language, directory, deadline, notes, "PNG" if detected == "image/png" else "JPEG")]
        if sum(len(page["text"].encode("utf-8")) for page in pages) > MAX_TEXT_BYTES or sum(len(page["words"]) for page in pages) > MAX_WORDS:
            raise OCRError("extraction_too_large", "Le texte extrait dépasse 64 Kio ou 5 000 mots ; diviser le document.")
        if time.monotonic() > deadline:
            raise OCRError("ocr_timeout", "Le délai maximal d'extraction est dépassé.", 504)
        candidates, candidate_notes = propose_candidates(pages)
        for page in pages:
            page.pop("_lines", None)
        return {"version": 1, "media_type": detected, "pages": pages, "candidates": candidates,
                "warnings": list(dict.fromkeys(notes + candidate_notes)), "review_required": True,
                "engine": {"name": "poppler+tesseract", "languages": language, "forced_ocr": force_ocr,
                           "confidence_note": "Score de reconnaissance Tesseract par mot, pas une probabilité d'exactitude du champ."}}


def _child_main():
    """Internal subprocess entrypoint; its parent enforces the overall wall limit."""
    try:
        if len(sys.argv) != 5 or sys.argv[1] != "--worker-child":
            raise OCRError("invalid_options", "Invocation OCR invalide.", 400)
        result = extract_document(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1), sys.argv[2], sys.argv[3], sys.argv[4] == "1")
        payload = {"status": 200, "result": result}
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise OCRError("extraction_too_large", "La sortie d'extraction dépasse la limite autorisée.")
    except OCRError as exc:
        encoded = json.dumps({"status": exc.status, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False).encode("utf-8")
    except Exception:
        encoded = b'{"status":500,"error":{"code":"ocr_failed","message":"Extraction indisponible."}}'
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    _child_main()
