"""Exercise the built production image, with synthetic credentials in a temporary volume.

Usage: python scripts/container_smoke.py --image admin-agent:ci --ocr-image admin-agent-ocr:ci
Requires Docker, requirements-production.txt and Pillow. Never targets a live client.
"""
import argparse
from datetime import date, timedelta
import hashlib
import io
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
from PIL import Image, ImageDraw, ImageFont


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='admin-agent:ci')
    parser.add_argument('--ocr-image', default='admin-agent-ocr:ci')
    args = parser.parse_args()
    if not shutil.which('docker'):
        raise SystemExit('Docker is required; this check was NOT run.')
    temporary = tempfile.TemporaryDirectory(prefix='admin-agent-container-')
    directory = Path(temporary.name) / 'client'
    name = 'admin-agent-smoke-' + secrets.token_hex(5)
    worker_name = name + '-ocr'
    network_name = name + '-private'
    origin = 'https://admin-ci.example.test'
    password = secrets.token_urlsafe(32)
    started = False
    worker_started = False
    network_started = False
    try:
        command('docker', 'network', 'create', '--internal', network_name)
        network_started = True
        network_meta = json.loads(command('docker', 'network', 'inspect', network_name))[0]
        assert network_meta['Internal'] is True
        command('docker', 'run', '-d', '--name', worker_name,
                '--network', network_name, '--network-alias', 'ocr',
                '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--pids-limit=64', '--memory=768m', '--cpus=1',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=128m',
                '--user', '10002:10002', args.ocr_image)
        worker_started = True
        worker_meta = json.loads(command('docker', 'inspect', worker_name))[0]
        assert worker_meta['HostConfig']['ReadonlyRootfs'] is True
        assert 'ALL' in worker_meta['HostConfig']['CapDrop']
        assert worker_meta['HostConfig']['Memory'] == 768 * 1024 * 1024
        assert worker_meta['HostConfig']['PidsLimit'] == 64
        assert not worker_meta['HostConfig']['PortBindings']
        assert all(mount['Type'] == 'tmpfs' for mount in worker_meta['Mounts'])
        assert set(worker_meta['NetworkSettings']['Networks']) == {network_name}
        assert not any('SECRET' in item.upper() or 'API_KEY' in item.upper() for item in worker_meta['Config']['Env'])
        assert command('docker', 'exec', worker_name, 'id', '-u') == '10002'
        health_command = "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8766/health',timeout=2).read()"
        for attempt in range(60):
            try:
                command('docker', 'exec', worker_name, 'python', '-c', health_command)
                break
            except subprocess.CalledProcessError:
                time.sleep(0.5)
        else:
            raise AssertionError('OCR worker did not become healthy within 30 seconds')
        # This evidence is non-sensitive: exact Debian and Python versions in the built image.
        print('OCR image package manifest:\n' + command('docker', 'exec', worker_name, 'cat', '/app/ocr-packages.txt'))
        init_client('ci-demo', 'admin-ci.example.test', directory, 'Client synthétique CI')
        config_path = directory / 'client.json'
        config = json.loads(config_path.read_text())
        enrollments = {}
        for username, role in [('ci-admin', 'admin'), ('ci-reader', 'reader')]:
            target = directory / f'{username}-enrollment.json'
            manage_user(config_path, 'user-add', username, password, role, target)
            enrollments[username] = json.loads(target.read_text())
        run = ['docker', 'run', '-d', '--name', name,
               '--network', network_name,
               '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
               '--pids-limit=128', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=128m',
               '--user', f"{config['uid']}:{config['gid']}",
               '-v', f'{directory / "data"}:/data',
               '-v', f'{directory / "secrets/session_secret"}:/run/secrets/session_secret:ro']
        env = {'ADMIN_AGENT_CLIENT_ID': 'ci-demo', 'ADMIN_AGENT_CLIENT_NAME': 'Client synthétique CI',
               'ADMIN_AGENT_PUBLIC_ORIGIN': origin, 'ADMIN_AGENT_DB': '/data/admin-agent.sqlite3',
               'ADMIN_AGENT_SESSION_SECRET_FILE': '/run/secrets/session_secret',
               'ADMIN_AGENT_BIND': '0.0.0.0', 'ADMIN_AGENT_PORT': '8765', 'ADMIN_AGENT_AI_ENABLED': '0',
               'ADMIN_AGENT_OCR_URL': 'http://ocr:8766'}
        for key, value in env.items():
            run.extend(['-e', key + '=' + value])
        run.append(args.image)
        command(*run)
        started = True
        # The Linux runner can reach its bridge directly. Internal networks do
        # not need (and may suppress) published ports. Keep app and worker private.
        runtime = json.loads(command('docker', 'inspect', name))[0]
        assert runtime['State']['Running'], 'Application container stopped during startup'
        app_ip = runtime['NetworkSettings']['Networks'][network_name]['IPAddress']
        assert app_ip, 'Application has no internal bridge address'
        assert not runtime['HostConfig']['PortBindings']
        address = 'http://' + app_ip + ':8765'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(path, method='GET', body=None, cookie=None, csrf=None, expected=200,
                    content_type='application/json', binary_response=False):
            headers = {'Host': 'admin-ci.example.test', 'Origin': origin, 'Content-Type': content_type}
            if cookie:
                headers['Cookie'] = cookie
            if csrf:
                headers['X-CSRF-Token'] = csrf
            data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
            req = urllib.request.Request(address + path, data=data, headers=headers, method=method)
            try:
                response = opener.open(req, timeout=75)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                payload = response.read()
                result = payload if binary_response else json.loads(payload) if payload else {}
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
        assert set(meta['NetworkSettings']['Networks']) == {network_name}

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
        # Exercise the actual Poppler/Tesseract image through the authenticated app.
        picture = Image.new('RGB', (1200, 520), 'white')
        draw = ImageDraw.Draw(picture)
        font = ImageFont.load_default(size=36)
        for index, line in enumerate(('Invoice number: INV-2026-001', 'Supplier: Synthetic Supplier',
                                      'Customer: Synthetic Customer', 'Total amount: 1200.00', 'Currency: EUR')):
            draw.text((50, 40 + index * 85), line, fill='black', font=font)
        stream = io.BytesIO()
        picture.save(stream, format='PNG')
        original = stream.getvalue()
        boundary = 'admin-agent-ci-' + secrets.token_hex(12)
        multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\neng\r\n'
                     f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic-invoice.png"\r\n'
                     'Content-Type: image/png\r\n\r\n').encode() + original + f'\r\n--{boundary}--\r\n'.encode()
        media = 'multipart/form-data; boundary=' + boundary
        request('/api/documents', 'POST', multipart, reader_cookie, reader['csrf_token'], 403, media)
        uploaded, _ = request('/api/documents', 'POST', multipart, cookie, csrf, 201, media)
        document = uploaded['document']
        document_id = document['id']
        assert document['sha256'] == hashlib.sha256(original).hexdigest()
        duplicated, _ = request('/api/documents', 'POST', multipart, cookie, csrf, 200, media)
        assert duplicated['document']['id'] == document_id
        source, _ = request(f'/api/documents/{document_id}/original', cookie=cookie, binary_response=True)
        assert source == original
        request(f'/api/documents/{document_id}/extract', 'POST', {'version': 0, 'language': 'eng'},
                reader_cookie, reader['csrf_token'], 403)
        extracted, _ = request(f'/api/documents/{document_id}/extract', 'POST', {'version': 0, 'language': 'eng'}, cookie, csrf)
        document = extracted['document']
        result = document['extraction']
        assert document['status'] == 'extracted' and document['extraction_version'] == 1
        assert len(result['pages']) == 1 and result['pages'][0]['method'] == 'ocr'
        assert result['candidates']['total_amount']['value'] == '1200.00'
        assert result['candidates']['total_amount']['page'] == 1
        assert result['candidates']['total_amount']['quote'] in result['pages'][0]['text']
        verified_payload = {'invoice_number': 'INV-2026-001', 'total_amount': '1200.00', 'currency': 'EUR'}
        draft = {'title': 'Facture OCR synthétique', 'description': 'Recette des conteneurs uniquement.',
                 'country': 'FR', 'skill_id': 'invoice-check', 'payload': verified_payload,
                 'extraction_version': 1, 'verified_fields': sorted(verified_payload), 'human_verified': False}
        request(f'/api/documents/{document_id}/create-task', 'POST', draft, cookie, csrf, 400)
        draft['human_verified'] = True
        linked, _ = request(f'/api/documents/{document_id}/create-task', 'POST', draft, cookie, csrf, 201)
        assert linked['task']['status'] == 'new'
        provenance = linked['task']['payload']['_document_source']
        assert provenance['sha256'] == document['sha256'] and provenance['human_verified'] is True
        assert provenance['reviewed_by'] == 'ci-admin'
        assert provenance['fields']['total_amount']['candidate']['page'] == 1
        repeated, _ = request(f'/api/documents/{document_id}/create-task', 'POST', draft, cookie, csrf)
        assert repeated['task']['id'] == linked['task']['id']
        assert len(request('/api/tasks', cookie=cookie)[0]['tasks']) == 2
        # Real built-image finance path. Dates stay valid when CI runs later.
        today = date.today()
        invoice_input = {'title': 'Facture finance synthétique', 'description': 'Recette conteneur, sans client réel.',
                         'country': 'FR', 'skill_id': 'invoice-check', 'payload': {
                             'invoice_number': 'FIN-CI-001', 'supplier': 'Fournisseur synthétique', 'customer': 'Client synthétique',
                             'issue_date': (today - timedelta(days=5)).isoformat(), 'due_date': (today + timedelta(days=30)).isoformat(),
                             'net_amount': '1000.00', 'vat_rate': '20.00', 'vat_amount': '200.00', 'total_amount': '1200.00',
                             'currency': 'EUR', 'paid': False, 'disputed': False}}
        created, _ = request('/api/tasks', 'POST', invoice_input, cookie, csrf, 201)
        finance_task = created['task']
        analyzed, _ = request(f'/api/tasks/{finance_task["id"]}/analyze', 'POST', {}, cookie, csrf)
        reviewed, _ = request(f'/api/tasks/{finance_task["id"]}/review', 'POST',
                              {'decision': 'approve', 'note': 'Contrôles synthétiques effectués', 'version': analyzed['task']['version']}, cookie, csrf)
        registered, _ = request('/api/finance/invoices/register', 'POST', {
            'task_id': finance_task['id'], 'task_version': reviewed['task']['version'], 'direction': 'receivable',
            'opening_paid_amount': '0.00', 'opening_as_of': (today - timedelta(days=1)).isoformat(),
            'opening_confirmed': True, 'evidence_ref': 'CI-OPENING-SYNTHETIC', 'disputed': False}, cookie, csrf)
        invoice = registered['invoice']
        simulation, _ = request('/api/finance/factoring/simulate', 'POST', {
            'invoice_id': invoice['id'], 'invoice_version': invoice['version'], 'advance_rate': '80.00',
            'fee_rate': '2.00', 'annual_interest_rate': '12.00', 'fixed_fee': '10.00',
            'funding_date': today.isoformat(), 'day_basis': 360}, cookie, csrf)
        assert simulation['simulation']['advance'] == '960.00'
        assert simulation['simulation']['reserve'] == '240.00'
        assert simulation['simulation']['net_cash'] == '916.40'
        bank = {'account_ref': 'CI-SYNTHETIC', 'csv_text': 'transaction_id,date,amount,currency,reference\nCI-BANK-1,' + today.isoformat() + ',600.00,EUR,FIN-CI-001\n'}
        preview, _ = request('/api/finance/bank/preview', 'POST', bank, cookie, csrf)
        bank['preview_digest'] = preview['preview']['preview_digest']
        imported, _ = request('/api/finance/bank/import', 'POST', bank, cookie, csrf)
        assert imported['import']['created'] == 1
        duplicate, _ = request('/api/finance/bank/import', 'POST', bank, cookie, csrf)
        assert duplicate['import']['created'] == 0
        transaction = imported['import']['transactions'][0]
        allocation = {'invoice_id': invoice['id'], 'invoice_version': invoice['version'],
                      'transaction_id': transaction['id'], 'transaction_version': transaction['version'],
                      'amount': '600.00', 'evidence_ref': 'CI-PAYMENT-SYNTHETIC', 'idempotency_key': 'CI-ALLOCATION-1'}
        request('/api/finance/allocations/confirm', 'POST', allocation, reader_cookie, reader['csrf_token'], 403)
        request('/api/finance/allocations/confirm', 'POST', allocation, cookie, csrf)
        request('/api/finance/allocations/confirm', 'POST', allocation, cookie, csrf, 409)
        ledger, _ = request('/api/finance/invoices', cookie=cookie)
        assert ledger['invoices'][0]['remaining_amount'] == '600.00'
        assert ledger['invoices'][0]['payment_status'] == 'partial'
        exported, _ = request('/api/export', cookie=cookie)
        assert len(exported['finance']['allocations']) == 1
        assert exported['finance']['bank_imports'][0]['csv_text'] == bank['csv_text']
        request('/api/logout', 'POST', {}, cookie, csrf)
        request('/api/tasks', cookie=cookie, expected=401)
        print('Production and OCR images: isolated runtime, MFA/CSRF/roles, real PNG OCR, original integrity, human confirmation, finance registration, factoring estimate, CSV import/replay, partial reconciliation, export and logout passed.')
    except Exception:
        for container, active in ((name, started), (worker_name, worker_started)):
            if active:
                subprocess.run(['docker', 'logs', '--tail', '60', container], check=False)
        raise
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if worker_started:
            subprocess.run(['docker', 'rm', '-f', worker_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if network_started:
            subprocess.run(['docker', 'network', 'rm', network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        temporary.cleanup()


if __name__ == '__main__':
    main()
