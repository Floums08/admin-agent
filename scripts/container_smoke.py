"""Exercise the built production image, with synthetic credentials in a temporary volume.

Usage: python scripts/container_smoke.py --image admin-agent:ci
Requires Docker and requirements-production.txt. Never targets a live client.
"""
import argparse
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from admin_agent.ops import init_client, manage_user
import pyotp


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='admin-agent:ci')
    args = parser.parse_args()
    if not shutil.which('docker'):
        raise SystemExit('Docker is required; this check was NOT run.')
    temporary = tempfile.TemporaryDirectory(prefix='admin-agent-container-')
    directory = Path(temporary.name) / 'client'
    name = 'admin-agent-smoke-' + secrets.token_hex(5)
    origin = 'https://admin-ci.example.test'
    password = secrets.token_urlsafe(32)
    started = False
    try:
        init_client('ci-demo', 'admin-ci.example.test', directory, 'Client synthétique CI')
        config_path = directory / 'client.json'
        config = json.loads(config_path.read_text())
        enrollments = {}
        for username, role in [('ci-admin', 'admin'), ('ci-reader', 'reader')]:
            target = directory / f'{username}-enrollment.json'
            manage_user(config_path, 'user-add', username, password, role, target)
            enrollments[username] = json.loads(target.read_text())
        run = ['docker', 'run', '-d', '--name', name,
               '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
               '--pids-limit=128', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
               '--user', f"{config['uid']}:{config['gid']}",
               '-p', '127.0.0.1::8765',
               '-v', f'{directory / "data"}:/data',
               '-v', f'{directory / "secrets/session_secret"}:/run/secrets/session_secret:ro']
        env = {'ADMIN_AGENT_CLIENT_ID': 'ci-demo', 'ADMIN_AGENT_CLIENT_NAME': 'Client synthétique CI',
               'ADMIN_AGENT_PUBLIC_ORIGIN': origin, 'ADMIN_AGENT_DB': '/data/admin-agent.sqlite3',
               'ADMIN_AGENT_SESSION_SECRET_FILE': '/run/secrets/session_secret',
               'ADMIN_AGENT_BIND': '0.0.0.0', 'ADMIN_AGENT_PORT': '8765', 'ADMIN_AGENT_AI_ENABLED': '0'}
        for key, value in env.items():
            run.extend(['-e', key + '=' + value])
        run.append(args.image)
        command(*run)
        started = True
        port = command('docker', 'port', name, '8765/tcp').rsplit(':', 1)[1]
        address = 'http://127.0.0.1:' + port

        def request(path, method='GET', body=None, cookie=None, csrf=None, expected=200):
            headers = {'Host': 'admin-ci.example.test', 'Origin': origin, 'Content-Type': 'application/json'}
            if cookie:
                headers['Cookie'] = cookie
            if csrf:
                headers['X-CSRF-Token'] = csrf
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(address + path, data=data, headers=headers, method=method)
            try:
                response = urllib.request.urlopen(req, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                payload = response.read()
                result = json.loads(payload) if payload else {}
                assert response.status == expected, f'{method} {path}: expected {expected}, got {response.status}'
                assert response.headers.get('X-Content-Type-Options') == 'nosniff'
                assert response.headers.get('Cache-Control') == 'no-store'
                new_cookie = response.headers.get('Set-Cookie')
                if new_cookie:
                    assert 'HttpOnly' in new_cookie and 'Secure' in new_cookie and 'SameSite=Strict' in new_cookie
                    jar = SimpleCookie(new_cookie)
                    cookie = '; '.join(f'{key}={value.value}' for key, value in jar.items())
                return result, cookie

        for attempt in range(60):
            try:
                request('/healthz')
                break
            except (OSError, AssertionError):
                time.sleep(0.5)
        else:
            raise AssertionError('Container did not become healthy within 30 seconds')
        request('/readyz')
        request('/api/tasks', expected=401)
        meta = json.loads(command('docker', 'inspect', name))[0]
        assert meta['HostConfig']['ReadonlyRootfs'] is True
        assert 'ALL' in meta['HostConfig']['CapDrop']
        assert command('docker', 'exec', name, 'id', '-u') != '0'

        def login(username):
            session, cookie = request('/api/session')
            assert session['authenticated'] is False
            code = pyotp.TOTP(enrollments[username]['totp_secret']).now()
            session, cookie = request('/api/login', 'POST', {'username': username, 'password': password, 'otp': code}, cookie, session['csrf_token'])
            assert session['authenticated'] and session['user']['username'] == username
            return session, cookie

        session, cookie = login('ci-admin')
        csrf = session['csrf_token']
        task_input = {'title': 'Recette conteneur synthétique', 'description': 'Une facture à classer.', 'country': 'FR', 'skill_id': 'admin-triage', 'payload': {}, 'idempotency_key': 'container-smoke-v1'}
        created, _ = request('/api/tasks', 'POST', task_input, cookie, csrf, 201)
        task_id = created['task']['id']
        analyzed, _ = request(f'/api/tasks/{task_id}/analyze', 'POST', {}, cookie, csrf)
        assert analyzed['task']['version'] > created['task']['version']
        exported, _ = request('/api/export', cookie=cookie)
        assert len(exported['tasks']) == 1
        # Flask's public GET asset catch-all makes this absent POST route a 405.
        # Verify both refusal and that no demonstration records appeared.
        request('/api/demo/seed', 'POST', {}, cookie, csrf, 405)
        remaining, _ = request('/api/tasks', cookie=cookie)
        assert len(remaining['tasks']) == 1
        request('/api/tasks', 'POST', task_input, cookie, None, 403)
        reader, reader_cookie = login('ci-reader')
        request('/api/tasks', cookie=reader_cookie)
        request('/api/tasks', 'POST', task_input, reader_cookie, reader['csrf_token'], 403)
        request('/api/export', cookie=reader_cookie, expected=403)
        request('/api/logout', 'POST', {}, cookie, csrf)
        request('/api/tasks', cookie=cookie, expected=401)
        print('Production image: non-root/read-only runtime, health/readiness, mandatory MFA, CSRF, named roles, dossier analysis, export and logout passed.')
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        temporary.cleanup()


if __name__ == '__main__':
    main()
