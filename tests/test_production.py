"""Production authentication, isolation and bounded-capacity regressions."""

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

PRODUCTION_AVAILABLE = all(importlib.util.find_spec(name) for name in ("flask", "pyotp", "cryptography"))
if PRODUCTION_AVAILABLE:
    import pyotp
    from admin_agent.auth import AuthStore, SESSION_TTL
    from admin_agent.errors import AppError
    from admin_agent.production import ProductionConfig, create_app, COOKIE_NAME
    from admin_agent.storage import Store, audit_actor, audit_guard


@unittest.skipUnless(PRODUCTION_AVAILABLE, "Installer requirements-production.txt pour la validation production")
class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = ProductionConfig("client-a", "Client A fictif", "https://client-a.test", Path(self.temp.name) / "db.sqlite3", secrets.token_hex(32).encode())
        self.app = create_app(self.config)
        self.auth = self.app.extensions["auth"]
        self.store = self.app.extensions["store"]
        self.timestamp = 1800000000
        self.auth.clock = lambda: self.timestamp
        self.password = "Mot-de-passe-synthetique-42"
        self.enrollment = self.auth.provision_user("admin-test", self.password, "admin")
        self.client = self.app.test_client()
        self.csrf = None

    def tearDown(self):
        self.temp.cleanup()

    def get(self, path, client=None, **kwargs):
        return (client or self.client).get(path, base_url=self.config.public_origin, **kwargs)

    def post(self, path, data, client=None, csrf=None, **kwargs):
        return (client or self.client).post(path, json=data, base_url=self.config.public_origin,
                                          headers={"Origin": self.config.public_origin, "X-CSRF-Token": csrf or self.csrf or ""}, **kwargs)

    def login(self, username="admin-test", secret=None, client=None):
        client = client or self.client
        bootstrap = self.get("/api/session", client=client).get_json()
        otp = pyotp.TOTP(secret or self.enrollment["totp_secret"]).at(self.timestamp)
        response = self.post("/api/login", {"username": username, "password": self.password, "otp": otp}, client=client, csrf=bootstrap["csrf_token"])
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        self.csrf = response.get_json()["csrf_token"]
        return response

    def task(self):
        return {"title": "Facture synthétique", "description": "Une facture à trier", "country": "FR", "skill_id": "admin-triage", "payload": {}, "idempotency_key": "synthetic-test"}

    def test_configuration_rejects_http_missing_secret_and_relative_storage(self):
        for changed in ({"public_origin": "http://client-a.test"}, {"public_origin": "https://client-a.test/"}, {"db_path": Path("relative.sqlite3")}, {"secret": b"short"}, {"client_id": "ab"}):
            with self.subTest(changed=list(changed)), self.assertRaises(ValueError):
                create_app(replace(self.config, **changed))
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            ProductionConfig.from_environment()
        with patch.dict(os.environ, {"ADMIN_AGENT_AI_ENABLED": "1"}), self.assertRaises(ValueError):
            create_app(self.config)

    def test_secret_file_configuration_reads_exact_bytes(self):
        path = Path(self.temp.name) / "session.key"
        path.write_bytes(self.config.secret + b"\n")
        env = {"ADMIN_AGENT_CLIENT_ID": "client-a", "ADMIN_AGENT_CLIENT_NAME": "Client A fictif", "ADMIN_AGENT_PUBLIC_ORIGIN": self.config.public_origin,
               "ADMIN_AGENT_DB": str(self.config.db_path), "ADMIN_AGENT_SESSION_SECRET_FILE": str(path)}
        with patch.dict(os.environ, env, clear=True):
            loaded = ProductionConfig.from_environment()
        self.assertEqual(self.config.secret, loaded.secret)
        self.assertEqual(self.config.db_path, loaded.db_path)

    def test_existing_local_dossiers_cannot_be_silently_assigned_to_a_client(self):
        local = Store(Path(self.temp.name) / "local.sqlite3")
        local.create(self.task())
        with self.assertRaises(ValueError):
            AuthStore(local, "client-b", "Client B", secrets.token_hex(32).encode())

    def test_health_endpoints_disclose_no_identity_and_readiness_fails_closed(self):
        self.assertEqual({"status": "ok"}, self.get("/healthz").get_json())
        self.assertEqual({"status": "ok"}, self.get("/readyz").get_json())
        with self.store.connection() as con:
            con.execute("UPDATE instance_identity SET schema_version=900")
        response = self.get("/readyz")
        self.assertEqual(503, response.status_code)
        self.assertEqual({"status": "unavailable"}, response.get_json())

    def test_unauthenticated_requests_cannot_read_data_or_export(self):
        for route in ("/api/tasks", "/api/skills", "/api/dashboard", "/api/export", "/api/health"):
            self.assertEqual(401, self.get(route).status_code, route)
        with self.get("/") as response:
            self.assertEqual(200, response.status_code)
        self.assertEqual(404, self.get("/.env").status_code)

    def test_totp_required_replay_rejected_and_window_bounded(self):
        self.csrf = self.get("/api/session").get_json()["csrf_token"]
        data = {"username": "admin-test", "password": self.password, "otp": pyotp.TOTP(self.enrollment["totp_secret"]).at(self.timestamp - 120)}
        self.assertEqual(401, self.post("/api/login", data).status_code)
        self.login()
        other = self.app.test_client()
        csrf = self.get("/api/session", client=other).get_json()["csrf_token"]
        data["otp"] = pyotp.TOTP(self.enrollment["totp_secret"]).at(self.timestamp)
        self.assertEqual(401, self.post("/api/login", data, client=other, csrf=csrf).status_code)
        self.timestamp += 30
        self.login(client=other)

    def test_password_and_mfa_secrets_are_not_stored_in_cleartext(self):
        response = self.login()
        token = self.client.get_cookie(COOKIE_NAME, domain="client-a.test").value
        with self.store.connection() as con:
            user = dict(con.execute("SELECT * FROM auth_users").fetchone())
            session = dict(con.execute("SELECT * FROM auth_sessions WHERE username IS NOT NULL").fetchone())
        serialized = json.dumps([user, session, self.auth.list_users(), response.get_json()])
        self.assertNotIn(self.password, serialized)
        self.assertNotIn(self.enrollment["totp_secret"], serialized)
        self.assertNotIn(token, serialized)
        self.assertTrue(user["password_hash"].startswith("scrypt:"))

    def test_idle_and_absolute_session_expiry(self):
        self.login()
        self.timestamp += 1801
        self.assertEqual(401, self.get("/api/tasks").status_code)
        self.login()
        token = self.client.get_cookie(COOKIE_NAME, domain="client-a.test").value
        with self.store.connection() as con:
            con.execute("UPDATE auth_sessions SET expires_at=? WHERE token_hash=?", (self.timestamp - 1, self.auth._digest("session", token)))
        self.assertEqual(401, self.get("/api/tasks").status_code)

    def test_password_reset_disable_and_mfa_reset_revoke_sessions(self):
        enrollment = self.auth.provision_user("operator-test", self.password, "operator")
        for action in (lambda: self.auth.reset_password("operator-test", self.password),
                       lambda: self.auth.set_user_enabled("operator-test", False),
                       lambda: self.auth.reset_mfa("operator-test")):
            self.timestamp += 30
            self.auth.set_user_enabled("operator-test", True)
            self.login("operator-test", enrollment["totp_secret"])
            action()
            self.assertEqual(401, self.get("/api/tasks").status_code)

    def test_named_actor_and_transactional_revocation_guard(self):
        self.login()
        response = self.post("/api/tasks", self.task())
        self.assertEqual(201, response.status_code)
        task_id = response.get_json()["task"]["id"]
        self.assertEqual("admin-test", self.store.events(task_id)[0]["details"]["actor"])
        token = self.client.get_cookie(COOKIE_NAME, domain="client-a.test").value
        self.auth.revoke_user_sessions("admin-test")
        marker = audit_guard.set(lambda con: self.auth.authorize_mutation(con, token))
        try:
            with self.assertRaises(AppError):
                self.store.update(task_id, {"title": "Should rollback", "version": 1})
        finally:
            audit_guard.reset(marker)
        self.assertEqual(1, self.store.get(task_id)["version"])
        self.assertEqual(1, len(self.store.events(task_id)))

    def test_operator_can_prepare_and_review_but_cannot_export_or_run_ai(self):
        enrollment = self.auth.provision_user("operator-test", self.password, "operator")
        self.login("operator-test", enrollment["totp_secret"])
        task = self.post("/api/tasks", self.task()).get_json()["task"]
        task = self.post(f"/api/tasks/{task['id']}/analyze", {}).get_json()["task"]
        response = self.post(f"/api/tasks/{task['id']}/review", {"decision": "approve", "version": task["version"], "note": "Vérifié"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(403, self.get("/api/export").status_code)
        self.assertEqual(403, self.post(f"/api/tasks/{task['id']}/analyze", {"use_ai": True}).status_code)
        self.assertIn(self.post("/api/demo/seed", {}).status_code, {404, 405})

    def test_production_list_is_compact_and_export_preserves_payload(self):
        self.login()
        task = self.task()
        task["payload"] = {"private": "synthetic-value"}
        task = self.post("/api/tasks", task).get_json()["task"]
        compact = self.get("/api/tasks").get_json()["tasks"][0]
        self.assertNotIn("payload", compact)
        self.assertNotIn("result", compact)
        self.assertTrue(compact["summary_only"])
        self.assertEqual("synthetic-value", self.get(f"/api/tasks/{task['id']}").get_json()["task"]["payload"]["private"])
        exported = self.get("/api/export")
        self.assertEqual(200, exported.status_code)
        self.assertEqual("synthetic-value", exported.get_json()["tasks"][0]["payload"]["private"])
        self.assertEqual("admin-test", exported.get_json()["events"][0]["details"]["actor"])

    def test_limits_are_persistent_and_account_bucket_survives_peer_change(self):
        token = self.auth.new_anonymous_session("peer-0")
        for index in range(5):
            with self.assertRaises(AppError) as caught:
                self.auth.login(token, "admin-test", "wrong", "000000", "peer-" + str(index))
            self.assertEqual(401, caught.exception.status)
        reopened = AuthStore(self.store, self.config.client_id, self.config.client_name, self.config.secret)
        reopened.clock = lambda: self.timestamp
        with self.assertRaises(AppError) as caught:
            reopened.login(token, "admin-test", self.password, pyotp.TOTP(self.enrollment["totp_secret"]).at(self.timestamp), "new-peer")
        self.assertEqual(429, caught.exception.status)

    def test_surrogate_username_is_generic_credential_error(self):
        self.csrf = self.get("/api/session").get_json()["csrf_token"]
        response = self.post("/api/login", {"username": "\ud800", "password": "bad", "otp": "000000"})
        self.assertEqual(401, response.status_code)
        self.assertEqual("invalid_credentials", response.get_json()["error"]["code"])

    def test_capacity_rejection_is_atomic_and_idempotent_retries_still_work(self):
        self.store.max_tasks = 1
        task, _ = self.store.create(self.task())
        self.assertFalse(self.store.create(self.task())[1])
        another = dict(self.task(), idempotency_key="second-test", title="Second")
        with self.assertRaises(AppError) as caught:
            self.store.create(another)
        self.assertEqual("capacity_reached", caught.exception.code)
        self.store.max_events = 1
        with self.assertRaises(AppError):
            self.store.update(task["id"], {"title": "Atomic rollback", "version": 1})
        self.assertEqual(1, self.store.get(task["id"])["version"])
        self.assertEqual(1, len(self.store.list()))

    def test_session_cookies_do_not_cross_isolated_instances(self):
        self.login()
        token = self.client.get_cookie(COOKIE_NAME, domain="client-a.test").value
        other_config = replace(self.config, client_id="client-b", client_name="Client B", public_origin="https://client-b.test", db_path=Path(self.temp.name) / "second.sqlite3", secret=secrets.token_hex(32).encode())
        other = create_app(other_config).test_client()
        other.set_cookie(COOKIE_NAME, token, domain="client-b.test")
        self.assertEqual(401, other.get("/api/tasks", base_url=other_config.public_origin).status_code)

    def test_anonymous_sessions_are_rate_limited_capped_and_expired_rows_cleaned(self):
        for _ in range(120):
            self.auth.new_anonymous_session("synthetic-peer")
        with self.assertRaises(AppError) as caught:
            self.auth.new_anonymous_session("synthetic-peer")
        self.assertEqual(429, caught.exception.status)
        with patch("admin_agent.auth.MAX_SESSIONS", 120), self.assertRaises(AppError) as caught:
            self.auth.new_anonymous_session("another-peer")
        self.assertEqual(503, caught.exception.status)
        self.timestamp += 901
        self.auth.new_anonymous_session("synthetic-peer")
        with self.store.connection() as con:
            self.assertEqual(1, con.execute("SELECT count(*) FROM auth_sessions").fetchone()[0])

    def test_invalid_unicode_payload_and_csrf_are_controlled_errors(self):
        self.login()
        response = self.post("/api/tasks", self.task(), csrf="é" * 64)
        self.assertEqual(403, response.status_code)
        payload = dict(self.task(), payload={"invalid": "\ud800"})
        self.assertEqual(400, self.post("/api/tasks", payload).status_code)
        self.assertEqual([], self.store.list())


if __name__ == "__main__":
    unittest.main()
