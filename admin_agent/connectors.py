"""Bounded, read-only source adapters. These run on the operator host, never via web URLs.

No adapter implements mail, uploads, remote writes, automatic approval or scheduling.
Network transport pins a validated public address while checking TLS for the original host.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import base64
import csv
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import time
from urllib.parse import quote, unquote, urlencode, urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

MAX_ITEMS = 20
MAX_BYTES = 5 * 1024 * 1024
MAX_LIST_BYTES = 1024 * 1024
MAX_DIRECTORY_ENTRIES = 1000
MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
INVOICE_FIELDS = {"invoice_number", "supplier", "customer", "issue_date", "due_date", "net_amount", "vat_rate", "vat_amount", "total_amount", "currency", "paid", "disputed", "paid_amount", "credit_amount"}


class ConnectorError(ValueError):
    """Expected refusal: message must never contain credentials or remote response bodies."""


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ConnectorError("Invalid text value in source or configuration.")
    return value.strip()


def _regular_bytes(path, limit=MAX_BYTES, secret=False):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ConnectorError("Use an absolute regular file path without symbolic links.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        # Traverse each directory with O_NOFOLLOW as well; checking is_symlink alone
        # leaves a parent-component race between inspection and opening the file.
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise ConnectorError("Connector file access requires a Linux/POSIX operator host.")
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in path.parts[1:-1]:
                next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(path.name, flags, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit or info.st_size < 1:
                raise ConnectorError("Source must be a nonempty regular file within the size limit.")
            if secret and (stat.S_IMODE(info.st_mode) != 0o600 or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())):
                raise ConnectorError("Credential file must be owned by the current operator with mode 0600.")
            content = stream.read(limit + 1)
            if len(content) > limit:
                raise ConnectorError("Source grew beyond the size limit.")
            return content
    except OSError as exc:
        raise ConnectorError("Source file is unreadable or not permitted.") from exc


def read_secret(path):
    try:
        secret = _regular_bytes(path, 4096, secret=True).decode("utf-8").rstrip("\r\n")
    except UnicodeError as exc:
        raise ConnectorError("Credential file must contain UTF-8 text.") from exc
    if not secret or any(ord(c) < 32 for c in secret):
        raise ConnectorError("Credential file contains an invalid value.")
    return secret


def _path(value):
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or len(value) > 2000:
        raise ConnectorError("Invalid configured source path.")
    decoded = unquote(value, errors="strict")
    if any(c in decoded for c in ("%", "\\", "?", "#")) or any(ord(c) < 32 for c in decoded) or any(p in {".", ".."} for p in decoded.split("/")) or "//" in decoded:
        raise ConnectorError("Encoded, ambiguous or traversing paths are refused.")
    return quote(decoded, safe="/-._~")


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout=15):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Numeric sockaddr avoids a second DNS lookup after validation.
        family, sockaddr = self.address
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(sockaddr)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class ReadOnlyHTTPS:
    """No proxies, no redirects, no private IPs and no caller-provided URL per request."""
    def __init__(self, base_url):
        try:
            url = urlsplit(base_url)
            if url.scheme != "https" or url.username or url.password or url.query or url.fragment or url.port not in {None, 443}:
                raise ConnectorError("Use a public HTTPS URL on port 443 without credentials, query or fragment.")
            self.host = url.hostname or ""
            if not re.fullmatch(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", self.host):
                raise ConnectorError("A public DNS hostname is required; IP literals and local names are refused.")
            self.root = _path(url.path or "/").rstrip("/") + "/"
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, ConnectorError):
                raise
            raise ConnectorError("Invalid HTTPS endpoint configuration.") from exc

    def child(self, href):
        try:
            url = urlsplit(href)
            if url.query or url.fragment or url.username or url.password:
                raise ConnectorError("Source returned an unsafe file reference.")
            if url.netloc and (url.scheme != "https" or url.hostname != self.host or url.port not in {None, 443}):
                raise ConnectorError("Source returned a reference outside the configured host.")
            if url.scheme and not url.netloc:
                raise ConnectorError("Source returned an unsafe file reference.")
            candidate = _path(url.path)
            if candidate.rstrip("/") == self.root.rstrip("/"):
                return None
            if not candidate.startswith(self.root):
                raise ConnectorError("Source returned a reference outside the configured folder.")
            relative = unquote(candidate[len(self.root):])
            if not relative or "/" in relative.rstrip("/"):
                raise ConnectorError("Only direct children of the configured folder are supported.")
            return candidate
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, ConnectorError):
                raise
            raise ConnectorError("Invalid remote file reference.") from exc

    def request(self, method, path=None, headers=None, body=None, query=None, limit=MAX_BYTES):
        if method not in {"GET", "PROPFIND"}:
            raise ConnectorError("This connector only supports read-only methods.")
        path = path or self.root
        if _path(path) != path or not path.startswith(self.root):
            raise ConnectorError("Request path is outside the configured root.")
        if query and (method != "GET" or not re.fullmatch(r"limit=20&page=[0-9]{1,6}&sortfield=t.rowid&sortorder=ASC", query)):
            raise ConnectorError("Only fixed invoice pagination parameters are supported.")
        try:
            answers = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
            if not answers or len(answers) > 32:
                raise ConnectorError("No bounded public DNS resolution is available.")
            for answer in answers:
                address = ipaddress.ip_address(answer[4][0])
                transition = isinstance(address, ipaddress.IPv6Address) and (
                    address.ipv4_mapped or address.sixtofour or address.teredo or
                    address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"))
                if not address.is_global or address.is_multicast or address.is_unspecified or address.is_reserved or transition:
                    raise ConnectorError("Private, local, reserved or mapped network destinations are refused.")
            connection = PinnedHTTPS(self.host, (answers[0][0], answers[0][4]))
            try:
                request_headers = {"Accept-Encoding": "identity", "User-Agent": "Admin-Agent-readonly/0.3", **(headers or {})}
                connection.request(method, path + ("?" + query if query else ""), body=body, headers=request_headers)
                response = connection.getresponse()
                if response.status not in {200, 207}:
                    raise ConnectorError("Remote read refused (authentication, permissions, redirect or server response).")
                if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                    raise ConnectorError("Compressed HTTP responses are refused.")
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > limit):
                    raise ConnectorError("Remote response exceeds the download limit.")
                started = time.monotonic()
                chunks, count = [], 0
                while count <= limit:
                    if time.monotonic() - started > 30:
                        raise ConnectorError("Remote response exceeded the time budget.")
                    chunk = response.read1(min(65536, limit + 1 - count))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    count += len(chunk)
                if count > limit:
                    raise ConnectorError("Remote response exceeds the download limit.")
                return b"".join(chunks)
            finally:
                connection.close()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if isinstance(exc, ConnectorError):
                raise
            raise ConnectorError("HTTPS source could not be read securely.") from exc


@dataclass
class SourceItem:
    connector_id: str
    source_key: str
    filename: str
    kind: str
    fetched_at: str
    sha256: str
    payload: dict = field(default_factory=dict)
    content: bytes = field(default=b"", repr=False)
    warnings: list = field(default_factory=list)

    def preview(self):
        return {"source_key": self.source_key, "filename": self.filename, "kind": self.kind,
                "fetched_at": self.fetched_at, "sha256": self.sha256, "size_bytes": len(self.content),
                "draft_fields": self.payload, "warnings": self.warnings,
                "review_required": True, "source_is_live_balance": False}


def _document(connector_id, key, filename, content):
    if len(content) > MAX_BYTES or not content:
        raise ConnectorError("Document size is outside the allowed range.")
    extension = Path(filename).suffix.lower()
    valid = ((extension == ".pdf" and content.startswith(b"%PDF-")) or
             (extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
             (extension in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff")))
    if not valid:
        raise ConnectorError("Document extension and PDF/PNG/JPEG signature must agree.")
    return SourceItem(connector_id, key, filename, "document", _now(), _digest(content), content=content,
                      warnings=["Original non analysé ; lancer l'extraction puis relire les champs."])


def scan_folder(config):
    root = Path(config["folder"])
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ConnectorError("Source folder must be an absolute directory without symbolic links.")
    names = []
    with os.scandir(root) as entries:
        for count, entry in enumerate(entries, 1):
            if count > MAX_DIRECTORY_ENTRIES:
                raise ConnectorError("Source folder has too many entries; use a dedicated intake folder.")
            if not entry.name.startswith(".") and Path(entry.name).suffix.lower() in MEDIA_TYPES:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise ConnectorError("Source folder contains an unsupported symbolic link or special file.")
                names.append(entry.name)
    if len(names) > MAX_ITEMS:
        raise ConnectorError("A scan accepts at most 20 documents; split the intake folder.")
    return [_document(config["id"], name, _text(name, 180), _regular_bytes(root / name)) for name in sorted(names)]


def _number(value, separator):
    value = _text(value, 40)
    pattern = r"[+-]?[0-9]+(?:" + re.escape(separator) + r"[0-9]{1,2})?"
    if not re.fullmatch(pattern, value):
        raise ConnectorError("Ambiguous number: grouping, mixed separators and more than two decimals are refused.")
    amount = Decimal(value.replace(separator, "."))
    if abs(amount) > Decimal("1000000000000"):
        raise ConnectorError("Amount exceeds the supported bound.")
    return format(amount, "f")


def _api_amount(value):
    # Dolibarr may serialize DECIMAL columns with trailing zero precision.
    # Accept exact cents only, with no rounding and no locale/grouping inference.
    value = _text(str(value), 48)
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]{1,10})?", value):
        raise ConnectorError("Dolibarr amount has an unsupported format.")
    amount = Decimal(value)
    if abs(amount) > Decimal("1000000000000") or amount != amount.quantize(Decimal("0.01")):
        raise ConnectorError("Dolibarr amount requires unsupported precision or exceeds the supported bound.")
    return format(amount.quantize(Decimal("0.01")), "f")


def _date(value, date_format):
    value = _text(value, 20)
    try:
        result = datetime.strptime(value, date_format).date()
        if result.strftime(date_format) != value:
            raise ValueError
        return result.isoformat()
    except ValueError as exc:
        raise ConnectorError("Date does not match the explicit configured format.") from exc


def scan_csv(config):
    content = _regular_bytes(config["file"])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ConnectorError("CSV must be UTF-8; no encoding is guessed.") from exc
    mapping = config["mapping"]
    if not isinstance(mapping, dict) or not mapping or set(mapping) - (INVOICE_FIELDS | {"source_id"}) or not {"source_id", "invoice_number"} <= set(mapping):
        raise ConnectorError("Provide an explicit mapping including source_id and invoice_number.")
    if len(set(mapping.values())) != len(mapping) or any(not isinstance(v, str) or not v for v in mapping.values()):
        raise ConnectorError("Each mapped CSV header must be unique and nonempty.")
    if config.get("delimiter") not in {",", ";", "\t"} or config.get("decimal_separator") not in {".", ","} or config.get("date_format") not in {"%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"}:
        raise ConnectorError("Set delimiter, decimal_separator and an explicit supported date_format.")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=config["delimiter"], strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or len(reader.fieldnames) > 50 or not set(mapping.values()) <= set(reader.fieldnames):
            raise ConnectorError("CSV headers are missing, duplicated or differ from the mapping.")
        result, seen = [], set()
        for row_number, row in enumerate(reader, 2):
            if len(result) >= MAX_ITEMS:
                raise ConnectorError("CSV import accepts at most 20 rows; split the export into batches.")
            if None in row or any(value is None for value in row.values()) or any(len(value) > 2000 for value in row.values()):
                raise ConnectorError("CSV row has missing/extra cells or an oversized value.")
            source_id = _text(row[mapping["source_id"]], 180)
            if source_id in seen:
                raise ConnectorError("Duplicate source_id in CSV; resolve before import.")
            seen.add(source_id)
            payload = {}
            for target, header in mapping.items():
                raw = row[header].strip()
                if target == "source_id" or not raw:
                    continue
                if target.endswith("_amount") or target == "vat_rate":
                    payload[target] = _number(raw, config["decimal_separator"])
                elif target in {"issue_date", "due_date"}:
                    payload[target] = _date(raw, config["date_format"])
                elif target in {"paid", "disputed"}:
                    if raw.lower() not in {"true", "false", "unknown"}:
                        raise ConnectorError("Boolean CSV fields accept only true, false, unknown or empty.")
                    if raw.lower() != "unknown":
                        payload[target] = raw.lower() == "true"
                else:
                    payload[target] = _text(raw)
            if not payload.get("invoice_number"):
                raise ConnectorError("CSV row is missing invoice_number.")
            raw_hash = _digest(_json(row))
            result.append(SourceItem(config["id"], source_id, f"Ligne CSV {row_number}", "invoice", _now(), raw_hash, payload=payload,
                                     warnings=["Instantané importé ; paiement et litige inconnus restent inconnus."]))
        return result
    except (csv.Error, UnicodeError, ValueError) as exc:
        if isinstance(exc, ConnectorError):
            raise
        raise ConnectorError("CSV source could not be parsed safely.") from exc


def scan_nextcloud(config, transport=None):
    transport = transport or ReadOnlyHTTPS(config["base_url"])
    username = _text(config["username"], 180)
    if ":" in username:
        raise ConnectorError("Nextcloud username cannot contain a colon.")
    authorization = base64.b64encode((username + ":" + read_secret(config["secret_file"])).encode()).decode()
    headers = {"Authorization": "Basic " + authorization, "Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
    body = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/></d:prop></d:propfind>'
    data = transport.request("PROPFIND", headers=headers, body=body, limit=MAX_LIST_BYTES)
    # UTF-8-only prevents UTF-16/32 from hiding a DTD from this pre-parser guard.
    try:
        xml = data.decode("utf-8-sig")
        if "\x00" in xml or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise ConnectorError("DTD, entities and non-UTF8 XML are refused.")
        root = ET.fromstring(xml)
    except (UnicodeError, ET.ParseError) as exc:
        raise ConnectorError("Invalid WebDAV XML response.") from exc
    if root.tag != "{DAV:}multistatus":
        raise ConnectorError("Expected a WebDAV multistatus response.")
    entries, seen = [], set()
    responses = root.findall("{DAV:}response")
    if len(responses) > MAX_DIRECTORY_ENTRIES:
        raise ConnectorError("WebDAV folder listing exceeds the entry limit.")
    for response in responses:
        href = response.findtext("{DAV:}href")
        if not href:
            raise ConnectorError("WebDAV response is missing its source reference.")
        path = transport.child(href)
        if path is None:
            continue
        properties = [p.find("{DAV:}prop") for p in response.findall("{DAV:}propstat") if re.fullmatch(r"HTTP/\d(?:\.\d)? 200(?: .*)?", p.findtext("{DAV:}status", ""))]
        if not properties:
            continue
        if any(p.find("{DAV:}resourcetype/{DAV:}collection") is not None for p in properties):
            continue
        filename = unquote(path.rsplit("/", 1)[-1])
        if Path(filename).suffix.lower() not in MEDIA_TYPES or filename.startswith("."):
            continue
        _text(filename, 180)
        if path in seen:
            raise ConnectorError("WebDAV returned a duplicate file reference.")
        seen.add(path)
        lengths = [p.findtext("{DAV:}getcontentlength") for p in properties if p.findtext("{DAV:}getcontentlength") is not None]
        if not lengths or any(not v.isdigit() or not 0 < int(v) <= MAX_BYTES for v in lengths):
            raise ConnectorError("WebDAV document size is missing or exceeds the limit.")
        entries.append((path, filename))
    if len(entries) > MAX_ITEMS:
        raise ConnectorError("WebDAV scan accepts at most 20 documents; use a dedicated intake folder.")
    return [_document(config["id"], path, name, transport.request("GET", path=path, headers={"Authorization": "Basic " + authorization}, limit=MAX_BYTES)) for path, name in sorted(entries)]


def scan_dolibarr(config, transport=None, page=0):
    if type(page) is not int or not 0 <= page <= 999999:
        raise ConnectorError("Dolibarr page must be an integer between 0 and 999999.")
    transport = transport or ReadOnlyHTTPS(config["base_url"])
    token = read_secret(config["secret_file"])
    raw = transport.request("GET", path=transport.root + "invoices", headers={"DOLAPIKEY": token, "Accept": "application/json"},
                            query=f"limit=20&page={page}&sortfield=t.rowid&sortorder=ASC", limit=MAX_LIST_BYTES)
    try:
        records = json.loads(raw, parse_float=Decimal, object_pairs_hook=_unique_pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConnectorError("Dolibarr returned invalid JSON.") from exc
    if not isinstance(records, list) or len(records) > MAX_ITEMS:
        raise ConnectorError("Dolibarr must return at most 20 invoice records per page.")
    currency = config.get("currency")
    if currency not in {"EUR", "USD", "GBP", "CHF", "CAD", "AUD"}:
        raise ConnectorError("Configure the Dolibarr company base currency explicitly.")
    try:
        zone = ZoneInfo(config["timezone"])
    except (KeyError, ValueError) as exc:
        raise ConnectorError("Configure the Dolibarr company timezone explicitly.") from exc
    results, seen = [], set()
    for record in records:
        if not isinstance(record, dict) or not re.fullmatch(r"[1-9][0-9]{0,17}", str(record.get("id", ""))):
            raise ConnectorError("Dolibarr invoice is missing a valid stable id.")
        source_id = str(record["id"])
        if source_id in seen:
            raise ConnectorError("Dolibarr returned duplicate invoice ids.")
        seen.add(source_id)
        # Hash the complete snapshot, including fields we do not yet map.
        serialized = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False).encode()
        payload = {"invoice_number": _text(record.get("ref")), "currency": currency, "supplier": _text(config["issuer"])}
        for source, target in (("total_ht", "net_amount"), ("total_tva", "vat_amount"), ("total_ttc", "total_amount")):
            if record.get(source) is not None:
                payload[target] = _api_amount(record[source])
        warnings = ["Facture client Dolibarr : montants en devise de base explicitement configurée.",
                    "Taux TVA, client, paiement et litige à confirmer ; aucun taux moyen ni statut de paiement déduit."]
        for source in ("status", "statut", "paye", "type"):
            if record.get(source) is not None:
                warnings.append("Valeur brute Dolibarr à interpréter dans l'ERP — " + source + " : " + _text(str(record[source]), 100))
        # Preserve explicit partial settlements/credits instead of losing evidence
        # while importing invoice totals. The deterministic engine blocks these
        # cases for manual reconciliation; it never sends a reminder.
        total = Decimal(payload["total_amount"]) if "total_amount" in payload else None
        for source, target in (("totalpaid", "paid_amount"), ("totalcreditnotes", "credit_amount"), ("totaldeposits", "amount_paid")):
            if record.get(source) is not None:
                amount = _api_amount(record[source])
                if Decimal(amount) != 0 and (source != "totalpaid" or total is None or Decimal(amount) != total):
                    payload[target] = amount
                    warnings.append("Règlement partiel, avoir ou acompte déclaré par la source : rapprochement manuel requis.")
        for source, target in (("date", "issue_date"), ("date_lim_reglement", "due_date")):
            value = record.get(source)
            if type(value) is int or isinstance(value, str) and re.fullmatch(r"[0-9]{1,11}", value):
                try:
                    payload[target] = datetime.fromtimestamp(int(value), zone).date().isoformat()
                except (ValueError, OverflowError, OSError):
                    warnings.append("Date source hors limites : saisie manuelle requise.")
            elif value is not None:
                warnings.append("Format de date source non reconnu : saisie manuelle requise.")
        results.append(SourceItem(config["id"], source_id, "Facture Dolibarr " + source_id, "invoice", _now(), _digest(serialized), payload=payload, warnings=warnings))
    return results


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConnectorError("Duplicate JSON source keys are refused.")
        result[key] = value
    return result


def validate_config(config):
    if not isinstance(config, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", str(config.get("id", ""))):
        raise ConnectorError("Connector id must be a stable lowercase identifier.")
    if config.get("kind") not in {"folder", "csv", "nextcloud", "dolibarr"}:
        raise ConnectorError("Unsupported connector kind.")
    required = {"folder": {"folder"}, "csv": {"file", "mapping", "delimiter", "decimal_separator", "date_format", "country"},
                "nextcloud": {"base_url", "username", "secret_file"}, "dolibarr": {"base_url", "secret_file", "country", "currency", "timezone", "issuer"}}[config["kind"]]
    if set(config) != required | {"id", "kind"}:
        raise ConnectorError("Connector configuration has missing or unsupported fields; never place secrets in JSON.")
    if "country" in config and config["country"] not in {"FR", "ES"}:
        raise ConnectorError("Configure invoice country as FR or ES.")
    return config


def scan(config, page=0, transport=None):
    validate_config(config)
    if config["kind"] != "dolibarr" and page:
        raise ConnectorError("Pagination is supported only for Dolibarr.")
    try:
        if config["kind"] == "folder":
            return scan_folder(config)
        if config["kind"] == "csv":
            return scan_csv(config)
        if config["kind"] == "nextcloud":
            return scan_nextcloud(config, transport)
        return scan_dolibarr(config, transport, page)
    except (OSError, KeyError, TypeError, UnicodeError, InvalidOperation, RecursionError) as exc:
        raise ConnectorError("Source or configuration is invalid; no remote change was made.") from exc
