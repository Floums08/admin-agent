"""Safety regressions for the local-only launcher; real Docker runs in pilot_smoke."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

from admin_agent.ops import OpsError
from scripts import pilot_local as pilot


class LocalPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pilot-local-unit-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "pilot"

    def initialize(self):
        # Some execution sandboxes cannot map UID10001; ownership is exercised in
        # the real Docker CI. chmod and private file creation are real here.
        with patch("admin_agent.ops.os.chown"):
            return pilot.initialize(self.directory)

    def model(self):
        self.initialize()
        marker, config = pilot.load_pilot(self.directory)
        common = {"read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]}
        app = {**common, "networks": {"private": {}, "documents": {}}, "image": marker["app_image"],
               "user": f"{config['uid']}:{config['gid']}", "volumes": [{"source": str(self.directory / "data"), "target": "/data"}],
               "environment": {"ADMIN_AGENT_CLIENT_ID": "invoice-pilot", "ADMIN_AGENT_PUBLIC_ORIGIN": marker["public_origin"],
                               "ADMIN_AGENT_DB": "/data/admin-agent.sqlite3", "ADMIN_AGENT_SESSION_SECRET_FILE": "/run/secrets/session_secret",
                               "ADMIN_AGENT_AI_ENABLED": "0", "ADMIN_AGENT_OCR_URL": "http://ocr:8766"}}
        ocr = {**common, "networks": {"documents": {}}, "image": marker["ocr_image"], "user": "10002:10002"}
        proxy = {**common, "networks": {"private": {}},
                 "ports": [{"host_ip": "127.0.0.1", "published": "8443", "target": 443, "protocol": "tcp"}],
                 "volumes": [{"source": str(pilot.ROOT / "deploy/Caddyfile.pilot"), "target": "/etc/caddy/Caddyfile", "read_only": True}]}
        model = {"services": {"app": app, "ocr": ocr, "proxy": proxy},
                 "networks": {"private": {"internal": True}, "documents": {"internal": True}},
                 "secrets": {"session_secret": {"file": str(self.directory / "secrets/session_secret")}}}
        return marker, config, model

    def test_private_init_no_credentials_and_replay_preserves_secrets(self):
        first = self.initialize()
        secret = (self.directory / "secrets/session_secret").read_text()
        marker_before = (self.directory / "pilot-local.json").read_bytes()
        second = pilot.initialize(self.directory)
        self.assertTrue(first["created"])
        self.assertFalse(first["credentials_created"])
        self.assertFalse(second["created"])
        self.assertFalse((self.directory / "data/admin-agent.sqlite3").exists())
        self.assertEqual(secret, (self.directory / "secrets/session_secret").read_text())
        self.assertEqual(marker_before, (self.directory / "pilot-local.json").read_bytes())
        self.assertNotIn(secret.strip(), json.dumps(first))
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        for name in ("client.json", "client.env", "pilot-local.json", "secrets/session_secret"):
            self.assertEqual(stat.S_IMODE((self.directory / name).stat().st_mode), 0o600)

    def test_existing_directory_or_configuration_is_never_replaced(self):
        self.directory.mkdir()
        original = self.directory / "existing-client.txt"
        original.write_text("keep")
        with self.assertRaises(OpsError):
            pilot.initialize(self.directory)
        self.assertEqual(original.read_text(), "keep")
        self.directory = Path(self.temp.name) / "new-pilot"
        self.initialize()
        with self.assertRaises(OpsError):
            pilot.initialize(self.directory, port=9443)
        self.assertEqual(pilot.load_pilot(self.directory)[0]["port"], 8443)

    def test_paths_refuse_aliases_repo_secrets_and_allow_nested_runtime(self):
        with self.assertRaises(OpsError):
            pilot.private_directory(Path(self.temp.name) / "alias/../pilot")
        linked = Path(self.temp.name) / "linked"
        linked.symlink_to(self.temp.name, target_is_directory=True)
        with self.assertRaises(OpsError):
            pilot.private_directory(linked / "pilot")
        outer = Path(self.temp.name) / "outer"
        root = outer / "admin-agent"
        for repository in (outer, root):
            (repository / ".git").mkdir(parents=True)
            (repository / ".git/HEAD").write_text("ref: refs/heads/main\n")
        with patch.object(pilot, "ROOT", root):
            self.assertEqual(pilot.private_directory(root / "runtime/pilot"), root / "runtime/pilot")
            with self.assertRaises(OpsError):
                pilot.private_directory(root / "examples/client")
            with self.assertRaises(OpsError):
                pilot.private_directory(outer / "private-client")

    def test_metadata_identity_and_private_paths_cannot_be_retargeted(self):
        self.initialize()
        config_path = self.directory / "client.json"
        config = json.loads(config_path.read_text())
        config["client_id"] = "real-client"
        config_path.write_text(json.dumps(config))
        with self.assertRaises(OpsError):
            pilot.load_pilot(self.directory)
        config["client_id"] = "invoice-pilot"
        config_path.write_text(json.dumps(config))
        data = self.directory / "data"
        data.rmdir()
        data.symlink_to(self.temp.name, target_is_directory=True)
        with self.assertRaises(OpsError):
            pilot.load_pilot(self.directory)

    def test_start_requires_enabled_admin_and_bound_pilot_identity(self):
        self.initialize()
        _, config = pilot.load_pilot(self.directory)
        with self.assertRaisesRegex(OpsError, "user-add"):
            pilot.require_admin(config)
        with sqlite3.connect(config["db"]) as connection:
            connection.executescript("CREATE TABLE instance_identity(client_id TEXT,client_name TEXT,schema_version INTEGER);"
                                     "INSERT INTO instance_identity VALUES('invoice-pilot','Synthetic',1);"
                                     "CREATE TABLE auth_users(username TEXT,role TEXT,enabled INTEGER);"
                                     "INSERT INTO auth_users VALUES('person','admin',0);")
        with patch("admin_agent.ops.os.chown"), self.assertRaises(OpsError):
            pilot.require_admin(config)
        with sqlite3.connect(config["db"]) as connection:
            connection.execute("UPDATE auth_users SET enabled=1")
        with patch("admin_agent.ops.os.chown"):
            pilot.require_admin(config)
        with sqlite3.connect(config["db"]) as connection:
            connection.execute("UPDATE instance_identity SET client_id='other-client'")
        with patch("admin_agent.ops.os.chown"), self.assertRaises(OpsError):
            pilot.require_admin(config)

    def test_merged_compose_rejects_public_ports_egress_and_worker_secrets(self):
        marker, config, model = self.model()
        pilot.validate_compose(model, self.directory, marker, config)
        cases = {
            "public binding": lambda value: value["services"]["proxy"]["ports"][0].update(host_ip="0.0.0.0"),
            "production port appended": lambda value: value["services"]["proxy"]["ports"].append({"published": "80", "target": 80}),
            "worker port": lambda value: value["services"]["ocr"].update(ports=[{"published": "8766", "target": 8766}]),
            "proxy internet": lambda value: value["services"]["proxy"]["networks"].update(edge={}),
            "internal network disabled": lambda value: value["networks"]["documents"].update(internal=False),
            "worker credentials": lambda value: value["services"]["ocr"].update(secrets=["session_secret"]),
            "root application": lambda value: value["services"]["app"].update(user="0:0"),
            "foreign client": lambda value: value["services"]["app"]["environment"].update(ADMIN_AGENT_CLIENT_ID="real-client"),
            "AI enabled": lambda value: value["services"]["app"]["environment"].update(ADMIN_AGENT_AI_ENABLED="1"),
            "public Caddy": lambda value: value["services"]["proxy"]["volumes"][0].update(source=str(pilot.ROOT / "deploy/Caddyfile")),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                unsafe = copy.deepcopy(model)
                mutate(unsafe)
                with self.assertRaises(OpsError):
                    pilot.validate_compose(unsafe, self.directory, marker, config)

    def test_compose_version_and_remote_daemon_refused_before_start(self):
        with patch.object(pilot.shutil, "which", return_value="/usr/bin/docker"), patch.object(pilot, "run", return_value="2.24.3"):
            with self.assertRaisesRegex(OpsError, "2.24.4"):
                pilot.check_compose()
        with patch.dict(os.environ, {"DOCKER_HOST": "ssh://remote.example.test"}), patch.object(pilot.shutil, "which", return_value="/usr/bin/docker"), patch.object(pilot, "run", return_value="2.40.0"):
            with self.assertRaisesRegex(OpsError, "local"):
                pilot.check_compose()
        with patch.dict(os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONTEXT": ""}), patch.object(pilot.shutil, "which", return_value="/usr/bin/docker"), patch.object(pilot, "run", return_value="2.40.0"):
            pilot.check_compose()

    def test_remote_context_takes_precedence_over_local_docker_host(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONTEXT": "remote"}), patch.object(pilot.shutil, "which", return_value="/usr/bin/docker"), patch.object(pilot, "run", side_effect=["2.40.0", '"ssh://remote.example.test"']) as calls:
            with self.assertRaisesRegex(OpsError, "local"):
                pilot.check_compose()
            self.assertEqual(calls.call_args_list[-1].args[0][-1], "remote")

    def test_host_compose_variables_do_not_override_pilot_configuration(self):
        with patch.dict(os.environ, {"PILOT_PORT": "443", "APP_UID": "0", "COMPOSE_FILE": "hostile.yaml", "CLIENT_ID": "real-client", "PATH": "/trusted/path"}):
            child = pilot.child_environment()
            self.assertNotIn("PILOT_PORT", child)
            self.assertNotIn("APP_UID", child)
            self.assertNotIn("COMPOSE_FILE", child)
            self.assertNotIn("CLIENT_ID", child)
            self.assertEqual(child["PATH"], "/trusted/path")


if __name__ == "__main__":
    unittest.main()
