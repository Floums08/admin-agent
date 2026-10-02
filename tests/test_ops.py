"""Operations tests use synthetic isolated databases and never a live client."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from admin_agent.ops import (OpsError, backup_database, init_client, load_config, main,
                             manage_user, preflight, restore_database, verify_backup)


class BackupOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "client.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE instance_identity(singleton INTEGER PRIMARY KEY,client_id TEXT,client_name TEXT,schema_version INTEGER);
            INSERT INTO instance_identity VALUES(1,'acme','ACME',1);
            CREATE TABLE records(id INTEGER PRIMARY KEY,note TEXT);
            INSERT INTO records VALUES(1,'Committed in WAL, not lost');
            CREATE TABLE auth_users(username TEXT PRIMARY KEY,password_hash TEXT,role TEXT,enabled INTEGER,totp_encrypted TEXT,last_totp_step INTEGER);
            INSERT INTO auth_users VALUES('alice','oldhash','admin',1,'oldencrypted',9);
            CREATE TABLE auth_sessions(token_hash TEXT PRIMARY KEY,username TEXT);
            INSERT INTO auth_sessions VALUES('stalehash','alice');
            CREATE TABLE auth_rate_limits(bucket TEXT PRIMARY KEY,count INTEGER);
            INSERT INTO auth_rate_limits VALUES('oldbucket',5);
        """)
        self.connection.commit()

    def snapshot(self):
        dest = self.root / "backup"
        result = backup_database(self.db, "acme", dest)
        self.assertFalse(result["encrypted"])
        self.assertEqual(stat.S_IMODE((dest / "database.sqlite3").stat().st_mode), 0o600)
        return dest

    def test_online_backup_includes_committed_wal_and_verified_manifest(self):
        self.assertTrue(Path(str(self.db) + "-wal").exists())
        dest = self.snapshot()
        manifest = verify_backup(dest, "acme")
        self.assertEqual(manifest["file"], "database.sqlite3")
        with sqlite3.connect(dest / "database.sqlite3") as con:
            self.assertEqual(con.execute("SELECT note FROM records").fetchone()[0], "Committed in WAL, not lost")
        self.assertEqual(set(p.name for p in dest.iterdir()), {"database.sqlite3", "manifest.json"})

    def test_cross_client_backup_and_restore_refused(self):
        with self.assertRaises(OpsError):
            backup_database(self.db, "other", self.root / "wrong")
        self.assertFalse((self.root / "wrong").exists())
        dest = self.snapshot()
        with self.assertRaises(OpsError):
            restore_database(dest, "other", self.root / "new.sqlite3")
        self.assertFalse((self.root / "new.sqlite3").exists())
        manifest = json.loads((dest / "manifest.json").read_text())
        manifest["client_id"] = "other"
        (dest / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(OpsError):
            verify_backup(dest, "other")

    def test_checksum_tampering_refused_before_restore(self):
        dest = self.snapshot()
        with (dest / "database.sqlite3").open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(OpsError, "checksum"):
            restore_database(dest, "acme", self.root / "new.sqlite3")
        self.assertFalse((self.root / "new.sqlite3").exists())

    def test_database_integrity_checked_even_with_matching_checksum(self):
        from admin_agent.ops import _sha256
        dest = self.snapshot()
        file = dest / "database.sqlite3"
        file.write_bytes(b"not a database")
        manifest = json.loads((dest / "manifest.json").read_text())
        manifest.update(sha256=_sha256(file), size_bytes=file.stat().st_size)
        (dest / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(OpsError):
            verify_backup(dest, "acme")

    def test_existing_target_and_sidecars_never_overwritten(self):
        dest = self.snapshot()
        original = self.db.read_bytes()
        with self.assertRaises(OpsError):
            restore_database(dest, "acme", self.db)
        self.assertEqual(self.db.read_bytes(), original)
        target = self.root / "reserved.sqlite3"
        Path(str(target) + "-wal").write_text("occupied")
        with self.assertRaises(OpsError):
            restore_database(dest, "acme", target)
        self.assertFalse(target.exists())
        with self.assertRaises(OpsError):
            backup_database(self.db, "acme", dest)

    def test_symlink_targets_and_backup_sources_refused(self):
        dest = self.snapshot()
        target = self.root / "symlink.sqlite3"
        target.symlink_to(self.root / "nonexistent")
        with self.assertRaises(OpsError):
            restore_database(dest, "acme", target)
        linked = self.root / "backup-link"
        linked.symlink_to(dest, target_is_directory=True)
        with self.assertRaises(OpsError):
            verify_backup(linked, "acme")

    def test_restore_revokes_and_quarantines_all_accounts(self):
        dest = self.snapshot()
        target = self.root / "restored.sqlite3"
        result = restore_database(dest, "acme", target)
        self.assertTrue(result["sessions_revoked"])
        with sqlite3.connect(target) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM auth_sessions").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT count(*) FROM auth_rate_limits").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT enabled,password_hash,totp_encrypted,last_totp_step FROM auth_users").fetchone(),
                             (0, "!restore-reset-required", "", -1))
            self.assertEqual(con.execute("SELECT username,password_reset,mfa_reset FROM ops_recovery_pending").fetchone(), ("alice", 0, 0))
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        # Restoration must never invalidate the original live source's users/sessions.
        self.assertEqual(self.connection.execute("SELECT enabled FROM auth_users").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM auth_sessions").fetchone()[0], 1)
        verify_backup(dest, "acme")


class ClientProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # This executor's root user has no mapping for UID10001. Container CI checks
        # real ownership; these unit tests assert provision logic without changing users.
        chown = patch("admin_agent.ops.os.chown")
        self.chown = chown.start()
        self.addCleanup(chown.stop)

    def test_init_secrets_are_private_unique_and_never_returned(self):
        first = init_client("acme", "admin.example.com", self.root / "first", "Acme France")
        second = init_client("other", "other.example.com", self.root / "second")
        c1, c2 = load_config(first["config"]), load_config(second["config"])
        secret = Path(c1["session_secret_file"]).read_text().strip()
        self.assertEqual(len(secret), 64)
        self.assertNotIn(secret, json.dumps(first))
        self.assertNotIn(secret, Path(first["config"]).read_text())
        self.assertNotEqual(secret, Path(c2["session_secret_file"]).read_text().strip())
        self.assertEqual(stat.S_IMODE(Path(c1["session_secret_file"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.root / "first").stat().st_mode), 0o700)
        with self.assertRaises(OpsError):
            init_client("acme", "admin.example.com", self.root / "first")

    def test_invalid_ids_domains_and_env_injection_refused(self):
        for slug, domain, name in [("a", "a.example.com", "A"), ("../acme", "a.example.com", "A"),
                                    ("acme", "https://example.com", "A"), ("acme", "a.example.com", "Acme\nEVIL=yes"),
                                    ("acme", "a.example.com", "$(touch bad)")]:
            with self.subTest(slug=slug, domain=domain, name=name), self.assertRaises(OpsError):
                init_client(slug, domain, self.root / "invalid", name)
        self.assertFalse((self.root / "invalid").exists())

    def test_preflight_never_creates_missing_database_or_claims_launch(self):
        result = init_client("acme", "admin.example.com", self.root / "client")
        config = load_config(result["config"])
        report = preflight(result["config"])
        self.assertFalse(report["launch_ready"])
        self.assertFalse(report["technical_ready"])
        self.assertFalse(Path(config["db"]).exists())
        self.assertTrue(all(row["status"] == "pending" for row in report["manual_launch_checks"]))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["preflight", "--config", result["config"]])
        self.assertEqual(code, 2)
        self.assertNotIn(Path(config["session_secret_file"]).read_text().strip(), output.getvalue())

    def test_backup_shell_fails_closed_without_environment(self):
        script = Path(__file__).resolve().parents[1] / "deploy/backup.sh"
        result = subprocess.run(["sh", str(script)], env={"PATH": os.environ["PATH"]}, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_mfa_output_nonterminal_without_file_is_refused_before_creation(self):
        result = init_client("acme", "admin.example.com", self.root / "client")
        with patch("sys.stdout.isatty", return_value=False), self.assertRaisesRegex(OpsError, "interactive terminal"):
            manage_user(result["config"], "user-add", "alice", "synthetic-long-password", "admin")
        self.assertFalse(Path(load_config(result["config"])["db"]).exists())

    def test_real_auth_provision_restore_recovery(self):
        try:
            import pyotp
            import cryptography
        except ImportError:
            self.skipTest("Production dependencies not installed")
        result = init_client("acme", "admin.example.com", self.root / "client")
        config = load_config(result["config"])
        enrollment = self.root / "enrollment.json"
        completed = manage_user(result["config"], "user-add", "alice", "synthetic-long-password", "admin", enrollment)
        self.assertTrue(completed["completed"])
        self.assertNotIn("totp_secret", completed)
        self.assertEqual(stat.S_IMODE(enrollment.stat().st_mode), 0o600)
        credentials = json.loads(enrollment.read_text())
        self.assertIn("totp_secret", credentials)
        bundle = self.root / "bundle"
        backup_database(config["db"], "acme", bundle)
        report = preflight(result["config"], bundle)
        self.assertTrue(report["technical_ready"], report)
        self.assertFalse(report["launch_ready"])
        restored = self.root / "recovered.sqlite3"
        restore_database(bundle, "acme", restored)
        config["db"] = str(restored)
        recovery_config = self.root / "recovery.json"
        recovery_config.write_text(json.dumps(config))
        with self.assertRaises(OpsError):
            manage_user(recovery_config, "user-enable", "alice")
        manage_user(recovery_config, "user-reset-password", "alice", "new-synthetic-password")
        with self.assertRaises(OpsError):
            manage_user(recovery_config, "user-enable", "alice")
        manage_user(recovery_config, "user-reset-mfa", "alice", enrollment_file=self.root / "new-enrollment.json")
        manage_user(recovery_config, "user-enable", "alice")
        with sqlite3.connect(restored) as con:
            self.assertEqual(con.execute("SELECT enabled FROM auth_users WHERE username='alice'").fetchone()[0], 1)
        self.assertTrue(preflight(recovery_config, bundle)["technical_ready"])


if __name__ == "__main__":
    unittest.main()
