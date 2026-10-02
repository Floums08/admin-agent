"""Synthetic source and operator-host connector regressions; no external accounts."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from admin_agent import connector_cli as cli
from admin_agent.connectors import (ConnectorError, MAX_BYTES, ReadOnlyHTTPS, PinnedHTTPS, _number,
                                    _regular_bytes, read_secret, scan, scan_csv, scan_dolibarr, scan_nextcloud)
from admin_agent.storage import Store


PDF = b"%PDF-1.4\nsynthetic test only\n%%EOF"
PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class FixtureTransport(ReadOnlyHTTPS):
    def __init__(self, root, responses):
        super().__init__(root)
        self.responses = list(responses)
        self.calls = []

    def request(self, method, **kwargs):
        self.calls.append((method, kwargs))
        return self.responses.pop(0)


def dav(href="/dav/intake/test.pdf", size=None):
    return (f'<d:multistatus xmlns:d="DAV:"><d:response><d:href>{href}</d:href><d:propstat><d:prop>'
            '<d:resourcetype/><d:getcontentlength>' + str(size or len(PDF)) + '</d:getcontentlength>'
            '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>').encode()


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = self.root / "secret"
        self.secret.write_text("synthetic-only-api-secret\n")
        self.secret.chmod(0o600)
        self.csv = self.root / "invoices.csv"
        self.csv.write_text("id;number;total;paid;disputed;date\none;TEST-1;120,00;unknown;;2026-10-02\n")
        self.csv_config = {"id": "csv-test", "kind": "csv", "file": str(self.csv), "country": "FR", "delimiter": ";", "decimal_separator": ",", "date_format": "%Y-%m-%d",
                           "mapping": {"source_id": "id", "invoice_number": "number", "total_amount": "total", "paid": "paid", "disputed": "disputed", "issue_date": "date"}}
        self.nextcloud = {"id": "nextcloud-test", "kind": "nextcloud", "base_url": "https://cloud.example.com/dav/intake/", "username": "readonly", "secret_file": str(self.secret)}
        self.dolibarr = {"id": "dolibarr-test", "kind": "dolibarr", "base_url": "https://erp.example.com/api/index.php/", "secret_file": str(self.secret),
                         "country": "ES", "currency": "EUR", "timezone": "Europe/Madrid", "issuer": "Synthetic company"}

    def test_csv_maps_decimal_and_preserves_unknown_states(self):
        item = scan(self.csv_config)[0]
        self.assertEqual(item.payload["total_amount"], "120.00")
        self.assertEqual(item.payload["issue_date"], "2026-10-02")
        self.assertNotIn("paid", item.payload)
        self.assertNotIn("disputed", item.payload)
        self.assertTrue(item.preview()["review_required"])

    def test_csv_explicit_boolean_and_date_format(self):
        self.csv.write_text("id;number;total;paid;disputed;date\none;TEST-1;120,00;true;false;02/10/2026\n")
        self.csv_config["date_format"] = "%d/%m/%Y"
        item = scan(self.csv_config)[0]
        self.assertIs(item.payload["paid"], True)
        self.assertIs(item.payload["disputed"], False)
        self.assertEqual(item.payload["issue_date"], "2026-10-02")

    def test_csv_refuses_ambiguous_numbers(self):
        for value in ("1,000", "1.000", "1.234,56", "1 234,56", "1e3", "NaN", "Infinity", "120,001", "=SUM(A1)"):
            with self.subTest(value=value), self.assertRaises(ConnectorError):
                _number(value, ",")

    def test_csv_refuses_inexact_dates_boolean_duplicate_ids(self):
        header = "id;number;total;paid;disputed;date\n"
        for rows in ("one;T;120,00;yes;;2026-10-02\n", "one;T;120,00;;;02/10/2026\n", "one;T;120,00;;;2026-02-30\n", "one;T;120,00;;;2026-10-02\none;T;120,00;;;2026-10-02\n"):
            self.csv.write_text(header + rows)
            with self.subTest(rows=rows), self.assertRaises(ConnectorError):
                scan(self.csv_config)

    def test_csv_refuses_duplicate_headers_extra_missing_cells_and_batch_overflow(self):
        header = "id;number;total;paid;disputed;date\n"
        for content in ("id;number;total;paid;disputed;date;id\none;T;1,00;;;2026-10-02;x\n", header + "one;T;1,00;;;2026-10-02;extra\n", header + "one;T;1,00\n", header + "".join(f"id{i};T;1,00;;;2026-10-02\n" for i in range(21))):
            self.csv.write_text(content)
            with self.subTest(content=content[:50]), self.assertRaises(ConnectorError):
                scan(self.csv_config)

    def test_folder_imports_only_supported_direct_children(self):
        folder = self.root / "intake"
        folder.mkdir()
        (folder / "document.pdf").write_bytes(PDF)
        (folder / "ignore.txt").write_text("not a document")
        (folder / "nested").mkdir()
        (folder / "nested" / "hidden.pdf").write_bytes(PDF)
        items = scan({"id": "folder-test", "kind": "folder", "folder": str(folder)})
        self.assertEqual([item.filename for item in items], ["document.pdf"])
        self.assertEqual(items[0].content, PDF)

    def test_folder_refuses_symlinks_wrong_signature_and_oversize(self):
        folder = self.root / "intake"
        folder.mkdir()
        file = folder / "document.pdf"
        file.symlink_to(self.secret)
        config = {"id": "folder-test", "kind": "folder", "folder": str(folder)}
        with self.assertRaises(ConnectorError):
            scan(config)
        file.unlink()
        file.write_text("not pdf")
        with self.assertRaises(ConnectorError):
            scan(config)
        with file.open("wb") as stream:
            stream.truncate(MAX_BYTES + 1)
        with self.assertRaises(ConnectorError):
            scan(config)

    def test_folder_refuses_more_than_twenty(self):
        for index in range(21):
            (self.root / f"{index}.pdf").write_bytes(PDF)
        with self.assertRaises(ConnectorError):
            scan({"id": "folder-test", "kind": "folder", "folder": str(self.root)})

    def test_private_secret_and_parent_symlink_requirements(self):
        self.assertEqual(read_secret(str(self.secret)), "synthetic-only-api-secret")
        self.secret.chmod(0o640)
        with self.assertRaises(ConnectorError):
            read_secret(str(self.secret))
        self.secret.chmod(0o600)
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ConnectorError):
            _regular_bytes(self.root / "alias" / "secret")
        with self.assertRaises(ConnectorError):
            read_secret("relative/secret")

    def test_secret_fifo_is_refused_without_blocking(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ConnectorError):
            read_secret(str(fifo))

    def test_url_policy_and_path_traversal(self):
        for url in ("http://cloud.example.com/a/", "https://user:pass@cloud.example.com/a/", "https://127.0.0.1/a/", "https://[::1]/a/", "https://localhost/a/", "https://cloud.example.com:8443/a/", "https://cloud.example.com/a/?secret=x", "https://cloud.example.com/a/#x", "https://cloud.example.com/a/../b/", "https://cloud.example.com/a/%252e%252e/", "https://cloud.example.com/a/%2f/b/"):
            with self.subTest(url=url), self.assertRaises(ConnectorError):
                ReadOnlyHTTPS(url)
        transport = ReadOnlyHTTPS("https://cloud.example.com/dav/intake/")
        for href in ("https://evil.example.com/dav/intake/file.pdf", "//evil.example.com/a.pdf", "/dav/other/file.pdf", "/dav/intake/../file.pdf", "/dav/intake/%2e%2e/file.pdf", "/dav/intake/sub/file.pdf", "/dav/intake/file.pdf?token=x", "javascript:test"):
            with self.subTest(href=href), self.assertRaises(ConnectorError):
                transport.child(href)
        self.assertEqual(transport.child("/dav/intake/invoice%20one.pdf"), "/dav/intake/invoice%20one.pdf")

    def test_network_rejects_private_mixed_and_rebound_dns(self):
        transport = ReadOnlyHTTPS("https://cloud.example.com/dav/")
        for address in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.2", "100.64.0.1", "::1", "::ffff:8.8.8.8", "2002:0a00:0001::", "64:ff9b::a00:1"):
            answer = (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            with self.subTest(address=address), patch("admin_agent.connectors.socket.getaddrinfo", return_value=PUBLIC + [answer]), patch("admin_agent.connectors.PinnedHTTPS") as connection:
                with self.assertRaises(ConnectorError):
                    transport.request("GET")
                connection.assert_not_called()

    def test_network_pins_address_and_never_re_resolves(self):
        transport = ReadOnlyHTTPS("https://cloud.example.com/dav/")
        response = MagicMock(status=200)
        response.getheader.side_effect = lambda key, default=None: {"Content-Length": "3"}.get(key, default)
        response.read1.side_effect = [b"abc", b""]
        with patch("admin_agent.connectors.socket.getaddrinfo", return_value=PUBLIC) as dns, patch("admin_agent.connectors.PinnedHTTPS") as connection:
            connection.return_value.getresponse.return_value = response
            self.assertEqual(transport.request("GET"), b"abc")
            dns.assert_called_once()
            connection.assert_called_once_with("cloud.example.com", (socket.AF_INET, ("93.184.216.34", 443)))
            connection.return_value.request.assert_called_once()
            connection.return_value.close.assert_called_once()

    def test_pinned_tls_uses_original_hostname_with_numeric_socket(self):
        connection = PinnedHTTPS("cloud.example.com", (socket.AF_INET, ("93.184.216.34", 443)))
        context = MagicMock()
        connection._context = context
        with patch("admin_agent.connectors.socket.socket") as socket_factory:
            connection.connect()
            socket_factory.return_value.connect.assert_called_once_with(("93.184.216.34", 443))
            context.wrap_socket.assert_called_once_with(socket_factory.return_value, server_hostname="cloud.example.com")

    def test_network_refuses_write_redirect_compression_and_oversize(self):
        transport = ReadOnlyHTTPS("https://cloud.example.com/dav/")
        with self.assertRaises(ConnectorError):
            transport.request("POST")
        with self.assertRaises(ConnectorError):
            transport.request("GET", path="/other/file.pdf")
        for status, headers, chunks in ((302, {}, []), (200, {"Content-Encoding": "gzip"}, []), (200, {"Content-Length": str(MAX_BYTES + 1)}, []), (200, {}, [b"x" * 11])):
            response = MagicMock(status=status)
            response.getheader.side_effect = lambda key, default=None: headers.get(key, default)
            response.read1.side_effect = chunks
            with patch("admin_agent.connectors.socket.getaddrinfo", return_value=PUBLIC), patch("admin_agent.connectors.PinnedHTTPS") as connection:
                connection.return_value.getresponse.return_value = response
                with self.assertRaises(ConnectorError):
                    transport.request("GET", limit=10)
                self.assertEqual(connection.return_value.request.call_count, 1)
                connection.return_value.close.assert_called_once()

    def test_network_error_does_not_reveal_secret_or_url(self):
        transport = ReadOnlyHTTPS("https://cloud.example.com/dav/")
        with patch("admin_agent.connectors.socket.getaddrinfo", side_effect=OSError("credential synthetic-only-api-secret https://private")):
            with self.assertRaises(ConnectorError) as caught:
                transport.request("GET")
        self.assertNotIn("synthetic-only", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_nextcloud_is_read_only_depth_one_and_safe(self):
        transport = FixtureTransport(self.nextcloud["base_url"], [dav(), PDF])
        item = scan_nextcloud(self.nextcloud, transport)[0]
        self.assertEqual(item.content, PDF)
        self.assertEqual([call[0] for call in transport.calls], ["PROPFIND", "GET"])
        self.assertEqual(transport.calls[0][1]["headers"]["Depth"], "1")
        self.assertNotIn("synthetic-only", json.dumps(item.preview()))

    def test_nextcloud_refuses_xxe_utf16_offroot_and_invalid_size(self):
        malicious = b'<!DOCTYPE x [<!ENTITY s SYSTEM "file:///etc/passwd">]><d:multistatus xmlns:d="DAV:"/>'
        for content in (malicious, malicious.decode().encode("utf-16"), dav("https://evil.example.com/dav/intake/test.pdf"), dav("/dav/intake/sub/file.pdf"), dav(size=MAX_BYTES + 1)):
            transport = FixtureTransport(self.nextcloud["base_url"], [content])
            with self.subTest(content=content[:40]), self.assertRaises(ConnectorError):
                scan_nextcloud(self.nextcloud, transport)
            self.assertEqual(len(transport.calls), 1)

    def test_dolibarr_maps_explicit_base_currency_and_no_payment_guess(self):
        record = {"id": "17", "ref": "DOL-17", "total_ht": "100.00", "total_tva": "20.00", "total_ttc": "120.00", "date": 1790892000, "date_lim_reglement": 1793487600, "paye": "0", "status": "1", "multicurrency_code": "USD"}
        transport = FixtureTransport(self.dolibarr["base_url"], [json.dumps([record]).encode()])
        item = scan_dolibarr(self.dolibarr, transport, page=2)[0]
        self.assertEqual(item.payload["currency"], "EUR")
        self.assertEqual(item.payload["total_amount"], "120.00")
        for field in ("paid", "disputed", "vat_rate", "customer"):
            self.assertNotIn(field, item.payload)
        method, request = transport.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(request["query"], "limit=20&page=2&sortfield=t.rowid&sortorder=ASC")
        self.assertEqual(request["headers"]["DOLAPIKEY"], "synthetic-only-api-secret")
        self.assertEqual(item.source_key, "17")

    def test_dolibarr_refuses_duplicates_nonfinite_and_too_many(self):
        for data in (b'[{"id":1,"id":2,"ref":"TEST"}]', b'[{"id":1,"ref":"TEST","total_ttc":NaN}]', json.dumps([{"id": 1, "ref": "TEST"}] * 21).encode(), b'[{"id":1,"ref":"A"},{"id":1,"ref":"B"}]'):
            with self.subTest(data=data[:50]), self.assertRaises(ConnectorError):
                scan_dolibarr(self.dolibarr, FixtureTransport(self.dolibarr["base_url"], [data]))

    def test_dolibarr_preserves_partial_settlement_evidence(self):
        record = {"id": "19", "ref": "DOL-19", "total_ttc": "120.00", "totalpaid": "40.00", "totalcreditnotes": "10.00", "totaldeposits": "5.00"}
        item = scan_dolibarr(self.dolibarr, FixtureTransport(self.dolibarr["base_url"], [json.dumps([record]).encode()]))[0]
        self.assertEqual(item.payload["paid_amount"], "40.00")
        self.assertEqual(item.payload["credit_amount"], "10.00")
        self.assertEqual(item.payload["amount_paid"], "5.00")
        self.assertNotIn("paid", item.payload)

    def test_dolibarr_accepts_trailing_zero_precision_without_rounding(self):
        record = {"id": "20", "ref": "DOL-20", "total_ttc": "120.00000000"}
        item = scan_dolibarr(self.dolibarr, FixtureTransport(self.dolibarr["base_url"], [json.dumps([record]).encode()]))[0]
        self.assertEqual(item.payload["total_amount"], "120.00")
        record["total_ttc"] = "120.001"
        with self.assertRaises(ConnectorError):
            scan_dolibarr(self.dolibarr, FixtureTransport(self.dolibarr["base_url"], [json.dumps([record]).encode()]))


class ConnectorImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "client.sqlite3"
        self.store = Store(self.db)
        with self.store.connection() as connection:
            connection.execute("CREATE TABLE instance_identity(singleton INTEGER PRIMARY KEY,client_id TEXT,client_name TEXT,schema_version INTEGER)")
            connection.execute("INSERT INTO instance_identity VALUES(1,'client-demo','Demo',1)")
        self.client = self.root / "client.json"
        self.client.write_text(json.dumps({"schema_version": 1, "client_id": "client-demo", "client_name": "Demo", "db": str(self.db), "uid": os.getuid(), "gid": os.getgid(), "session_secret_file": str(self.root / "unused-session"), "restic_password_file": str(self.root / "unused-restic")}))
        self.csv = self.root / "invoices.csv"
        self.csv.write_text("id;number;total\none;TEST-1;120,00\n")
        self.config = {"id": "csv-test", "kind": "csv", "file": str(self.csv), "country": "FR", "delimiter": ";", "decimal_separator": ",", "date_format": "%Y-%m-%d", "mapping": {"source_id": "id", "invoice_number": "number", "total_amount": "total"}}
        self.config_path = self.root / "connectors.json"
        self.write_config()

    def write_config(self, client_id="client-demo"):
        self.config_path.write_text(json.dumps({"schema_version": 1, "client_id": client_id, "connectors": [self.config]}))

    def test_preview_no_database_mutation_and_explicit_import_unreviewed(self):
        preview = cli.run(self.client, self.config_path, "csv-test")
        self.assertEqual(preview["mode"], "preview")
        self.assertEqual(self.store.list(), [])
        result = cli.run(self.client, self.config_path, "csv-test", apply=True)
        self.assertTrue(result["completed"])
        self.assertTrue(result["outcomes"][0]["created"])
        task = self.store.list()[0]
        self.assertEqual(task["status"], "new")
        self.assertIsNone(task["result"])
        self.assertEqual(task["skill_id"], "invoice-check")
        self.assertNotIn("paid", task["payload"])
        self.assertIn("fetched_at", task["payload"]["_connector_source"])
        self.assertEqual(self.store.events()[0]["details"]["actor"], "connector_cli:csv-test")

    def test_repeat_is_idempotent_and_changed_source_refuses(self):
        cli.run(self.client, self.config_path, "csv-test", apply=True)
        again = cli.run(self.client, self.config_path, "csv-test", apply=True)
        self.assertEqual(again["outcomes"][0]["status"], "already_imported")
        self.csv.write_text("id;number;total\none;TEST-1;125,00\n")
        changed = cli.run(self.client, self.config_path, "csv-test", apply=True)
        self.assertFalse(changed["completed"])
        self.assertEqual(changed["outcomes"][0]["status"], "refused")
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.list()[0]["payload"]["total_amount"], "120.00")

    def test_changed_mapping_and_country_refuse_with_same_raw_hash(self):
        item = scan_csv(self.config)[0]
        cli.import_invoice(self.store, item, "FR")
        with self.assertRaises(ConnectorError):
            cli.import_invoice(self.store, item, "ES")
        item.payload["currency"] = "USD"
        with self.assertRaises(ConnectorError):
            cli.import_invoice(self.store, item, "FR")

    def test_connector_provenance_cannot_be_forged_or_removed(self):
        from admin_agent.errors import AppError
        item = scan_csv(self.config)[0]
        task, _ = cli.import_invoice(self.store, item, "FR")
        forged = {key: task[key] for key in ("title", "description", "skill_id", "country", "payload")}
        with self.assertRaises(AppError):
            self.store.create(forged)
        changed = self.store.update(task["id"], {"version": task["version"], "payload": {"invoice_number": "TEST-1", "total_amount": "130.00"}})
        provenance = changed["payload"]["_connector_source"]
        self.assertEqual(provenance["imported_values"]["total_amount"], "120.00")
        self.assertIn("total_amount", provenance["changed_since_import"])
        again, created = cli.import_invoice(self.store, item, "FR")
        self.assertFalse(created)
        self.assertEqual(again["payload"]["total_amount"], "130.00")

    def test_database_permissions_restored_after_success_and_scan_failure(self):
        self.db.chmod(0o644)
        cli.run(self.client, self.config_path, "csv-test", apply=True)
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        with patch("admin_agent.connector_cli._secure_db") as secure, patch("admin_agent.connector_cli.scan", side_effect=ConnectorError("failed")):
            with self.assertRaises(ConnectorError):
                cli.run(self.client, self.config_path, "csv-test")
        secure.assert_called_once()

    def test_database_sidecar_symlink_refuses(self):
        sidecar = Path(str(self.db) + "-shm")
        sidecar.unlink(missing_ok=True)
        sidecar.symlink_to(self.csv)
        with self.assertRaises(ConnectorError):
            cli.run(self.client, self.config_path, "csv-test", apply=True)

    def test_document_import_no_extraction_and_source_change_refuses(self):
        folder = self.root / "intake"
        folder.mkdir()
        document = folder / "invoice.pdf"
        document.write_bytes(PDF)
        self.config = {"id": "folder-test", "kind": "folder", "folder": str(folder)}
        self.write_config()
        result = cli.run(self.client, self.config_path, "folder-test", apply=True)
        self.assertTrue(result["completed"])
        from admin_agent.documents import DocumentStore
        record = DocumentStore(self.store).get(result["outcomes"][0]["id"])
        self.assertEqual(record["status"], "uploaded")
        self.assertIsNone(record["extraction"])
        self.assertEqual(record["sources"][0]["source_key"], "invoice.pdf")
        again = cli.run(self.client, self.config_path, "folder-test", apply=True)
        self.assertFalse(again["outcomes"][0]["created"])
        document.write_bytes(PDF + b"changed")
        changed = cli.run(self.client, self.config_path, "folder-test", apply=True)
        self.assertEqual(changed["outcomes"][0]["status"], "refused")
        self.assertEqual(changed["outcomes"][0]["error"], "source_changed")

    def test_mismatched_client_refused_before_reading_source(self):
        self.write_config(client_id="other-client")
        with patch("admin_agent.connector_cli.scan") as scanner, self.assertRaises(ConnectorError):
            cli.run(self.client, self.config_path, "csv-test", apply=True)
        scanner.assert_not_called()
        self.assertEqual(self.store.list(), [])

    def test_database_identity_mismatch_never_relabels_or_queries_source(self):
        with self.store.connection() as connection:
            connection.execute("UPDATE instance_identity SET client_id='other-client'")
        with patch("admin_agent.connector_cli.scan") as scanner, self.assertRaises(ValueError):
            cli.run(self.client, self.config_path, "csv-test", apply=True)
        scanner.assert_not_called()
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("SELECT client_id FROM instance_identity").fetchone()[0], "other-client")

    def test_duplicate_json_plaintext_credentials_and_unsupported_configs_refused(self):
        self.config_path.write_text('{"schema_version":1,"client_id":"client-demo","client_id":"client-demo","connectors":[]}')
        with self.assertRaises(ConnectorError):
            cli.load_connectors(self.config_path, "client-demo")
        self.config["password"] = "must-not-be-json"
        self.write_config()
        with self.assertRaises(ConnectorError):
            cli.load_connectors(self.config_path, "client-demo")

    def test_cli_error_is_sanitized_and_nonzero(self):
        with patch("admin_agent.connector_cli.run", side_effect=OSError("TOP-SECRET")), contextlib.redirect_stderr(io.StringIO()) as output:
            result = cli.main(["--client-config", str(self.client), "--connector-config", str(self.config_path), "--connector", "csv-test"])
        self.assertEqual(result, 2)
        self.assertNotIn("TOP-SECRET", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["remote_writes"])


if __name__ == "__main__":
    unittest.main()
