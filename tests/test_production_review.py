"""Independent adversarial production regressions; synthetic accounts only."""

from pathlib import Path
import importlib.util
import json
import tempfile
import threading
import unittest

from admin_agent.errors import AppError
from admin_agent.ops import backup_database, restore_database
from admin_agent.storage import Store

HAS_PRODUCTION = all(importlib.util.find_spec(name) for name in ("flask", "pyotp", "cryptography"))
if HAS_PRODUCTION:
    import pyotp
    from admin_agent.auth import AuthStore
    from admin_agent.production import COOKIE_NAME, ProductionConfig, create_app


@unittest.skipUnless(HAS_PRODUCTION, "Production dependencies absent; install requirements-production.txt for this security gate.")
class IndependentAuthReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "client.sqlite3"
        self.store = Store(self.path)
        self.secret = b"72" * 32
        self.auth = AuthStore(self.store, "client-a", "Synthetic Client A", self.secret)
        self.timestamp = 1800000000
        self.auth.clock = lambda: self.timestamp
        self.password = "Synthetic-review-only-3971"
        self.enrollment = self.auth.provision_user("review-admin", self.password, "admin")

    def tearDown(self):
        self.temp.cleanup()

    def login(self, token=None):
        token = token or self.auth.new_anonymous_session("review-peer")
        otp = pyotp.TOTP(self.enrollment["totp_secret"]).at(self.timestamp)
        return self.auth.login(token, "review-admin", self.password, otp, "review-peer")

    def test_concurrent_totp_replay_allows_only_one_new_session(self):
        tokens = [self.auth.new_anonymous_session("review-peer") for _ in range(2)]
        barrier = threading.Barrier(2)
        successes, denials, unexpected = [], [], []

        def attempt(token):
            try:
                barrier.wait(timeout=5)
                successes.append(self.login(token))
            except AppError as exc:
                denials.append(exc.status)
            except Exception as exc:
                unexpected.append(type(exc).__name__)

        workers = [threading.Thread(target=attempt, args=(token,)) for token in tokens]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual([], unexpected)
        self.assertEqual(1, len(successes))
        self.assertEqual([401], denials)
        with self.store.connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM auth_sessions WHERE username IS NOT NULL").fetchone()[0]
        self.assertEqual(1, count)

    def test_exhausted_preauth_quota_cannot_prevent_session_revocation(self):
        token = self.login()
        # Reproduce a shared reverse-proxy peer whose preauthentication quota is full.
        for _ in range(119):
            self.auth.rate_limit("session-mint", "review-peer", 120)
        try:
            self.auth.logout(token, "review-peer")
        except AppError:
            # A replacement preauth session may be refused; the old session must be gone.
            pass
        self.assertIsNone(self.auth.get_session(token))

    def test_wrong_client_binding_fails_without_relabeling_database(self):
        with self.assertRaises(ValueError):
            AuthStore(self.store, "client-b", "Synthetic Client B", self.secret)
        with self.store.connection() as connection:
            identity = connection.execute("SELECT client_id,client_name FROM instance_identity").fetchone()
        self.assertEqual(("client-a", "Synthetic Client A"), tuple(identity))
        self.assertEqual("review-admin", self.auth.list_users()[0]["username"])

    def test_restore_cannot_resurrect_old_credentials_or_sessions(self):
        token = self.login()
        destination = Path(self.temp.name) / "backup"
        backup_database(self.path, "client-a", destination)
        # A password reset after the snapshot must not be undone into usable credentials.
        self.auth.reset_password("review-admin", "A-new-synthetic-password-5081")
        restored = Path(self.temp.name) / "restored.sqlite3"
        restore_database(destination, "client-a", restored)
        recovered = AuthStore(Store(restored), "client-a", "Synthetic Client A", self.secret)
        recovered.clock = lambda: self.timestamp + 30
        self.assertIsNone(recovered.get_session(token))
        self.assertFalse(recovered.list_users()[0]["enabled"])
        # Enabling alone cannot make the stale password + historical MFA seed usable.
        recovered.set_user_enabled("review-admin", True)
        preauth = recovered.new_anonymous_session("recovery-peer")
        with self.assertRaises(AppError) as caught:
            recovered.login(preauth, "review-admin", self.password,
                            pyotp.TOTP(self.enrollment["totp_secret"]).at(self.timestamp + 30),
                            "recovery-peer")
        self.assertEqual(401, caught.exception.status)


@unittest.skipUnless(HAS_PRODUCTION, "Production dependencies absent; install requirements-production.txt for this security gate.")
class IndependentHTTPReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.origin = "https://client-a.test"
        self.app = create_app(ProductionConfig(
            client_id="client-a", client_name="Synthetic Client A", public_origin=self.origin,
            db_path=Path(self.temp.name) / "client.sqlite3", secret=b"81" * 32))
        self.auth = self.app.extensions["auth"]
        self.store = self.app.extensions["store"]
        self.password = "Synthetic-HTTP-review-8371"
        self.enrollment = {}

    def tearDown(self):
        self.temp.cleanup()

    def anonymous(self):
        browser = self.app.test_client()
        response = browser.get("/api/session", base_url=self.origin)
        self.assertEqual(200, response.status_code)
        return browser, response.get_json()["csrf_token"]

    def credentials(self, role):
        username = "review-" + role
        if role not in self.enrollment:
            self.enrollment[role] = self.auth.provision_user(username, self.password, role)
        return {"username": username, "password": self.password,
                "otp": pyotp.TOTP(self.enrollment[role]["totp_secret"]).at(self.auth.clock())}

    def post(self, browser, path, csrf, data, **kwargs):
        headers = {"Origin": self.origin, "X-CSRF-Token": csrf}
        headers.update(kwargs.pop("headers", {}))
        return browser.post(path, base_url=self.origin, headers=headers, json=data, **kwargs)

    def login(self, role="admin"):
        browser, csrf = self.anonymous()
        response = self.post(browser, "/api/login", csrf, self.credentials(role))
        self.assertEqual(200, response.status_code, response.get_json())
        return browser, response.get_json()["csrf_token"]

    def test_login_csrf_bound_to_origin_and_own_preauth_session(self):
        browser, csrf = self.anonymous()
        other, other_csrf = self.anonymous()
        credentials = self.credentials("admin")
        for headers in ({}, {"Origin": self.origin},
                        {"Origin": "https://evil.test", "X-CSRF-Token": csrf},
                        {"Origin": self.origin, "X-CSRF-Token": other_csrf}):
            with self.subTest(headers=headers):
                response = browser.post("/api/login", base_url=self.origin, headers=headers, json=credentials)
                self.assertEqual(403, response.status_code)
        response = self.post(browser, "/api/login", csrf, credentials)
        self.assertEqual(200, response.status_code)
        self.assertFalse(other.get("/api/session", base_url=self.origin).get_json()["authenticated"])

    def test_cookie_rotation_attributes_and_logout_destroy_old_token(self):
        browser, preauth_csrf = self.anonymous()
        old_cookie = browser.get_cookie(COOKIE_NAME, domain="client-a.test").value
        response = self.post(browser, "/api/login", preauth_csrf, self.credentials("admin"))
        self.assertEqual(200, response.status_code)
        cookie = response.headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cookie)
        self.assertNotIn("Domain=", cookie)
        logged_cookie = browser.get_cookie(COOKIE_NAME, domain="client-a.test").value
        self.assertNotEqual(old_cookie, logged_cookie)
        replay = self.app.test_client()
        replay.set_cookie(COOKIE_NAME, old_cookie, domain="client-a.test")
        self.assertEqual(401, replay.get("/api/tasks", base_url=self.origin).status_code)
        csrf = response.get_json()["csrf_token"]
        self.assertEqual(403, self.post(browser, "/api/logout", "wrong", {}).status_code)
        self.assertEqual(200, browser.get("/api/tasks", base_url=self.origin).status_code)
        self.assertEqual(200, self.post(browser, "/api/logout", csrf, {}).status_code)
        replay.set_cookie(COOKIE_NAME, logged_cookie, domain="client-a.test")
        self.assertEqual(401, replay.get("/api/export", base_url=self.origin).status_code)

    def test_forwarded_headers_cannot_bypass_host_tls_or_auth(self):
        browser = self.app.test_client()
        response = browser.get("/api/session", base_url="https://evil.test",
                               headers={"X-Forwarded-Host": "client-a.test"})
        self.assertEqual(403, response.status_code)
        response = browser.get("/api/session", base_url="http://client-a.test",
                               headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(403, response.status_code)
        response = browser.get("/api/export", base_url=self.origin,
                               headers={"X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1;proto=https"})
        self.assertEqual(401, response.status_code)

    def test_reader_cannot_write_review_seed_export_or_call_external_actions(self):
        task, _ = self.store.create({"title": "Synthetic review case", "description": "Facture à vérifier",
                                    "country": "FR", "skill_id": "admin-triage", "payload": {}})
        browser, csrf = self.login("reader")
        original = self.store.get(task["id"])
        routes = [("/api/tasks", {}), (f"/api/tasks/{task['id']}/update", {"version": 1, "title": "Changed"}),
                  (f"/api/tasks/{task['id']}/analyze", {}),
                  (f"/api/tasks/{task['id']}/review", {"version": 1, "decision": "approve"})]
        for route, data in routes:
            with self.subTest(route=route):
                self.assertEqual(403, self.post(browser, route, csrf, data).status_code)
        self.assertEqual(403, browser.get("/api/export", base_url=self.origin).status_code)
        for route in ("/api/demo/seed", "/api/send-email", "/api/pay", "/api/submit"):
            with self.subTest(route=route):
                self.assertIn(self.post(browser, route, csrf, {}).status_code, (404, 405))
        self.assertEqual(original, self.store.get(task["id"]))
        self.assertEqual(1, len(self.store.events()))

    def test_role_change_immediately_revokes_existing_http_session(self):
        browser, _ = self.login("operator")
        self.assertEqual(200, browser.get("/api/tasks", base_url=self.origin).status_code)
        self.auth.set_user_role("review-operator", "reader")
        self.assertEqual(401, browser.get("/api/tasks", base_url=self.origin).status_code)

    def test_bad_json_and_oversize_body_have_no_business_side_effect(self):
        browser, csrf = self.login()
        headers = {"Origin": self.origin, "X-CSRF-Token": csrf, "Content-Type": "application/json"}
        for raw in ('{"title":"one","title":"two"}', '{"payload":{"amount":NaN}}', '[]'):
            with self.subTest(raw=raw):
                response = browser.post("/api/tasks", base_url=self.origin, headers=headers, data=raw)
                self.assertEqual(400, response.status_code)
        response = browser.post("/api/tasks", base_url=self.origin, headers=headers,
                                data=json.dumps({"title": "x" * 70000}))
        self.assertEqual(413, response.status_code)
        self.assertEqual([], self.store.list())
        self.assertEqual([], self.store.events())

    def test_tiny_bookkeeping_input_cannot_persist_explosive_analysis_result(self):
        browser, csrf = self.login("operator")
        response = self.post(browser, "/api/tasks", csrf, {
            "title": "Synthetic incomplete bookkeeping", "description": "Missing metadata",
            "country": "FR", "skill_id": "bookkeeping-pack",
            "payload": {"period": "2026-10", "documents": [{} for _ in range(300)]}})
        self.assertEqual(201, response.status_code)
        task = response.get_json()["task"]
        response = self.post(browser, f"/api/tasks/{task['id']}/analyze", csrf, {})
        self.assertEqual(413, response.status_code)
        current = self.store.get(task["id"])
        self.assertEqual(task["version"], current["version"])
        self.assertIsNone(current["result"])


if __name__ == "__main__":
    unittest.main()
