"""CI-only rehearsal of the actual local pilot stack; synthetic data, no live target.

Build both images first. This starts Caddy + production app + OCR, verifies TLS
against this stack's own CA, then removes its containers, volumes and temporary
records. It never installs a trusted CA into the host/browser trust store.
"""
import argparse
import hashlib
from http.cookies import SimpleCookie
import json
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from admin_agent.ops import manage_user
import pyotp


def command(*args):
    # Do not print captured subprocess diagnostics: an enrollment must stay private.
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Pilot subprocess failed: " + " ".join(str(x) for x in args[:3]))
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="admin-agent:ci")
    parser.add_argument("--ocr-image", default="admin-agent-ocr:ci")
    args = parser.parse_args()
    if not shutil.which("docker"):
        raise SystemExit("Docker is required; pilot container check was NOT run.")
    with tempfile.TemporaryDirectory(prefix="admin-agent-pilot-ci-") as temporary:
        directory = Path(temporary) / "pilot"
        script = str(ROOT / "scripts/pilot_local.py")
        project = None
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        origin = f"https://pilot.localhost:{port}"
        password = secrets.token_urlsafe(32)
        try:
            command(sys.executable, script, "init", "--directory", str(directory),
                    "--port", str(port), "--app-image", args.image, "--ocr-image", args.ocr_image)
            # The CLI returns this summary only after validating the merged model.
            config = json.loads(command(sys.executable, script, "config", "--directory", str(directory)))
            project = config["name"]
            enrollment_path = directory / "secrets" / "ci-enrollment.json"
            manage_user(directory / "client.json", "user-add", "pilot-ci-admin", password,
                        "admin", enrollment_path)
            enrollment = json.loads(enrollment_path.read_text())
            command(sys.executable, script, "up", "--directory", str(directory), "--no-build")
            command(sys.executable, script, "certificate", "--directory", str(directory))
            context = ssl.create_default_context(cafile=str(directory / "tls/pilot-root-ca.crt"))
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
            original_lookup = socket.getaddrinfo

            def local_lookup(host, *lookup_args, **kwargs):
                return original_lookup("127.0.0.1" if host == "pilot.localhost" else host, *lookup_args, **kwargs)

            def request(path, method="GET", body=None, cookie=None, csrf=None, expected=200, media="application/json"):
                headers = {"Origin": origin, "Content-Type": media}
                if cookie:
                    headers["Cookie"] = cookie
                if csrf:
                    headers["X-CSRF-Token"] = csrf
                data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
                with patch("socket.getaddrinfo", side_effect=local_lookup):
                    try:
                        response = opener.open(urllib.request.Request(origin + path, data=data, headers=headers, method=method), timeout=75)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        assert response.status == expected, f"{method} {path}: {response.status}, expected {expected}"
                        payload = response.read()
                        if path.endswith("/original"):
                            return payload, cookie
                        result = json.loads(payload)
                        new_cookie = response.headers.get("Set-Cookie")
                        if new_cookie:
                            assert all(flag in new_cookie for flag in ("Secure", "HttpOnly", "SameSite=Strict"))
                            jar = SimpleCookie(new_cookie)
                            cookie = "; ".join(f"{key}={value.value}" for key, value in jar.items())
                        return result, cookie

            request("/readyz")
            request("/api/tasks", expected=401)
            session, cookie = request("/api/session")
            request("/api/login", "POST", {"username": "pilot-ci-admin", "password": password, "otp": "invalid"}, cookie, session["csrf_token"], expected=401)
            session, cookie = request("/api/login", "POST", {"username": "pilot-ci-admin", "password": password,
                                       "otp": pyotp.TOTP(enrollment["totp_secret"]).now()}, cookie, session["csrf_token"])
            assert session["authenticated"] and session["capabilities"]["ocr_enabled"]
            csrf = session["csrf_token"]
            assert request("/api/tasks", cookie=cookie)[0]["tasks"] == []
            pack = directory / "fixtures"
            command(sys.executable, str(ROOT / "scripts/pilot_fixtures.py"), "--output", str(pack))
            manifest = json.loads((pack / "expected/manifest.json").read_text())
            assert manifest["synthetic"] is True and len(manifest["cases"]) == 10
            case = manifest["cases"][0]
            original = (pack / case["file"]).read_bytes()
            boundary = "pilot-smoke-" + secrets.token_hex(12)
            multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nfra\r\n'
                         f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.pdf"\r\n'
                         'Content-Type: application/pdf\r\n\r\n').encode() + original + f"\r\n--{boundary}--\r\n".encode()
            uploaded, _ = request("/api/documents", "POST", multipart, cookie, csrf, 201,
                                  "multipart/form-data; boundary=" + boundary)
            document = uploaded["document"]
            document_id = document["id"]
            assert document["sha256"] == hashlib.sha256(original).hexdigest()
            extraction, _ = request(f"/api/documents/{document_id}/extract", "POST",
                                    {"version": 0, "language": "fra", "force_ocr": True}, cookie, csrf)
            document = extraction["document"]
            assert all(page["method"] == "ocr" for page in document["extraction"]["pages"])
            assert document["extraction"]["candidates"]["total_amount"]["value"] == case["expected_fields"]["total_amount"]
            # Synthetic simulation of the explicit review API; no claim of human review.
            payload = {"total_amount": case["expected_fields"]["total_amount"]}
            draft = {"title": "Synthetic pilot smoke", "description": "Synthetic CI only", "skill_id": "invoice-check",
                     "country": "FR", "payload": payload, "verified_fields": list(payload),
                     "extraction_version": document["extraction_version"], "human_verified": False}
            request(f"/api/documents/{document_id}/create-task", "POST", draft, cookie, csrf, 400)
            draft["human_verified"] = True
            linked, _ = request(f"/api/documents/{document_id}/create-task", "POST", draft, cookie, csrf, 201)
            assert linked["task"]["status"] == "new"
            assert linked["task"]["payload"]["_document_source"]["sha256"] == document["sha256"]
            assert request(f"/api/documents/{document_id}/original", cookie=cookie)[0] == original
            request("/api/logout", "POST", {}, cookie, csrf)
            request("/api/tasks", cookie=cookie, expected=401)
            containers = command("docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.ID}}").split()
            assert len(containers) == 3
            for container in containers:
                metadata = json.loads(command("docker", "inspect", container))[0]
                service = metadata["Config"]["Labels"]["com.docker.compose.service"]
                bindings = metadata["HostConfig"]["PortBindings"] or {}
                if service == "proxy":
                    assert bindings == {"443/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}
                else:
                    assert not bindings
                assert metadata["HostConfig"]["ReadonlyRootfs"] is True
            print("PASS: actual local pilot Compose, verified TLS, loopback-only port, MFA refusal/login, empty database, synthetic pack, real French OCR, review requirement, original integrity and logout. No customer go-live or human timings measured.")
        finally:
            if project:
                compose = ["docker", "compose", "--project-name", project, "--env-file", str(directory / "client.env"),
                           "-f", str(ROOT / "compose.yaml"), "-f", str(ROOT / "compose.pilot.yaml")]
                subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], cwd=ROOT,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    main()
