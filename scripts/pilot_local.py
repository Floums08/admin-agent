"""Start a synthetic invoice pilot on loopback HTTPS using the production services.

Linux / WSL2, Python 3.11+ and Docker Compose >=2.24.4. No DNS changes,
credential generation, CA trust installation, remote clients or outgoing messages.
Create named accounts separately through admin_agent.ops user-add.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from admin_agent.ops import OpsError, _identity, _private_write, _readonly_db, _secure_db, init_client, load_config

CLIENT_ID = "invoice-pilot"
DOMAIN = "pilot.localhost"
MIN_COMPOSE = (2, 24, 4)
DEFAULT_DIRECTORY = ROOT / "runtime" / CLIENT_ID
RUNTIME_ENV_KEYS = {"CLIENT_ID", "CLIENT_NAME", "DOMAIN", "CLIENT_DATA_DIR", "SESSION_SECRET_PATH",
                    "APP_UID", "APP_GID", "APP_IMAGE", "OCR_IMAGE", "PILOT_PORT", "COMPOSE_FILE",
                    "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES", "COMPOSE_ENV_FILES"}


def private_directory(value):
    path = Path(value).absolute()
    if ".." in path.parts:
        raise OpsError("Le chemin du pilote ne doit pas contenir '..'.")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise OpsError("Le répertoire du pilote et ses parents doivent être sans lien symbolique.")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", str(path)):
        raise OpsError("Utiliser un chemin Linux absolu sans espaces ni caractères d'interpolation.")
    for parent in (path, *path.parents):
        git_marker = parent / ".git"
        if git_marker.is_file() or (git_marker / "HEAD").is_file():
            if not (parent == ROOT and path.is_relative_to(ROOT / "runtime")):
                raise OpsError("Dans le dépôt, stocker le pilote uniquement sous runtime/ ignoré par Git ; sinon choisir un répertoire privé hors dépôt.")
            break
    return path


def project_name(directory):
    return "invoice-pilot-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]


def image_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:@-]{0,240}", value):
        raise OpsError("Nom d'image invalide.")
    return value


def initialize(directory, port=8443, app_image="admin-agent:pilot-local", ocr_image="admin-agent-ocr:pilot-local"):
    directory = private_directory(directory)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise OpsError("Choisir un port local entre 1024 et 65535.")
    app_image, ocr_image = image_name(app_image), image_name(ocr_image)
    if directory.exists():
        marker, _ = load_pilot(directory)
        if (marker["port"], marker["app_image"], marker["ocr_image"]) != (port, app_image, ocr_image):
            raise OpsError("Le pilote existe avec une autre configuration ; aucun remplacement effectué.")
        return {"created": False, "directory": str(directory), "url": marker["public_origin"], "credentials_created": False}
    init_client(CLIENT_ID, DOMAIN, directory, "Pilote factures — données fictives")
    config_path = directory / "client.json"
    config = json.loads(config_path.read_text())
    config["public_origin"] = f"https://{DOMAIN}:{port}"
    # These two files have just been created by init_client in a new private directory.
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    lines = {"CLIENT_ID": CLIENT_ID, "CLIENT_NAME": "'Pilote factures — données fictives'", "DOMAIN": DOMAIN,
             "CLIENT_DATA_DIR": str(directory / "data"), "SESSION_SECRET_PATH": str(directory / "secrets/session_secret"),
             "APP_UID": str(config["uid"]), "APP_GID": str(config["gid"]), "APP_IMAGE": app_image,
             "OCR_IMAGE": ocr_image, "PILOT_PORT": str(port)}
    (directory / "client.env").write_text("".join(f"{key}={value}\n" for key, value in lines.items()))
    marker = {"schema_version": 1, "synthetic_only": True, "client_id": CLIENT_ID,
              "directory": str(directory), "project": project_name(directory), "port": port,
              "public_origin": config["public_origin"], "app_image": app_image, "ocr_image": ocr_image}
    _private_write(directory / "pilot-local.json", json.dumps(marker, indent=2) + "\n")
    (directory / "tls").mkdir(mode=0o700)
    return {"created": True, "directory": str(directory), "url": config["public_origin"], "credentials_created": False,
            "next_step": "Créer un compte nominatif avec python -m admin_agent.ops user-add avant up."}


def load_pilot(directory):
    directory = private_directory(directory)
    if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise OpsError("Répertoire pilote absent ou non privé ; init est requis.")
    try:
        for name in ("pilot-local.json", "client.json", "client.env"):
            path = directory / name
            if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise OpsError("Configuration pilote attendue en fichier régulier privé 0600.")
        for relative in ("data", "secrets", "tls"):
            path = directory / relative
            if path.is_symlink() or not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise OpsError("Les sous-répertoires du pilote doivent rester privés et sans lien symbolique.")
        secret = directory / "secrets/session_secret"
        if secret.is_symlink() or not secret.is_file() or stat.S_IMODE(secret.stat().st_mode) != 0o600:
            raise OpsError("Le secret de session doit rester un fichier régulier privé 0600.")
        marker = json.loads((directory / "pilot-local.json").read_text())
        config = load_config(directory / "client.json")
        port = marker["port"]
        expected_origin = f"https://{DOMAIN}:{port}"
        if (set(marker) != {"schema_version", "synthetic_only", "client_id", "directory", "project", "port", "public_origin", "app_image", "ocr_image"}
                or marker["schema_version"] != 1 or marker["synthetic_only"] is not True
                or marker["client_id"] != CLIENT_ID or marker["directory"] != str(directory)
                or marker["project"] != project_name(directory) or type(port) is not int or not 1024 <= port <= 65535
                or marker["public_origin"] != expected_origin or config["public_origin"] != expected_origin
                or config["client_id"] != CLIENT_ID or config["domain"] != DOMAIN
                or config["db"] != str(directory / "data/admin-agent.sqlite3")
                or config["session_secret_file"] != str(directory / "secrets/session_secret")
                or type(config["uid"]) is not int or config["uid"] <= 0
                or type(config["gid"]) is not int or config["gid"] <= 0):
            raise OpsError("Configuration non conforme au pilote synthétique local ; opération refusée.")
        image_name(marker["app_image"])
        image_name(marker["ocr_image"])
        return marker, config
    except (KeyError, ValueError, TypeError, OSError) as exc:
        if isinstance(exc, OpsError):
            raise
        raise OpsError("Configuration pilote invalide ou illisible.") from exc


def child_environment():
    # Host environment must not silently override this pilot's explicit env file.
    return {key: value for key, value in os.environ.items() if key not in RUNTIME_ENV_KEYS}


def run(args, capture=True):
    result = subprocess.run(args, cwd=ROOT, env=child_environment(), text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, check=False)
    if result.returncode:
        raise OpsError("Commande Docker refusée ou échouée ; vérifier le moteur, la configuration et les journaux locaux.")
    return result.stdout.strip() if capture else ""


def check_compose():
    if not shutil.which("docker"):
        raise OpsError("Docker est requis ; installer Docker Engine ou Docker Desktop intégré à WSL2.")
    text = run(["docker", "compose", "version", "--short"])
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", text)
    if not match or tuple(int(part) for part in match.groups()) < MIN_COMPOSE:
        raise OpsError("Docker Compose 2.24.4 ou plus récent est requis pour remplacer les ports publics en sécurité.")
    # A remote Docker context would deploy the pilot on another machine despite
    # loopback port bindings. This kit is intentionally limited to a local daemon.
    context = os.environ.get("DOCKER_CONTEXT")
    if context and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", context):
        raise OpsError("Nom de contexte Docker non pris en charge.")
    # Docker gives DOCKER_CONTEXT precedence over DOCKER_HOST.
    endpoint = None if context else os.environ.get("DOCKER_HOST")
    if not endpoint:
        try:
            inspect = ["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"]
            if context:
                inspect.append(context)
            endpoint = json.loads(run(inspect))
        except ValueError as exc:
            raise OpsError("Contexte Docker local non vérifiable.") from exc
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise OpsError("Ce kit accepte seulement un moteur Docker local par socket Unix ; aucun déploiement distant.")


def compose_command(directory, marker):
    return ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(directory / "client.env"),
            "-p", marker["project"], "-f", str(ROOT / "compose.yaml"), "-f", str(ROOT / "compose.pilot.yaml")]


def validate_compose(model, directory, marker, config):
    """Fail closed on the actual merged model, before Docker can bind a port."""
    try:
        services = model["services"]
        if set(services) != {"app", "ocr", "proxy"}:
            raise ValueError()
        for name, service in services.items():
            if (service.get("privileged") or service.get("network_mode") or service.get("pid") or service.get("ipc")
                    or not service.get("read_only") or "ALL" not in service.get("cap_drop", [])
                    or "no-new-privileges:true" not in service.get("security_opt", [])):
                raise ValueError()
            networks = set(service["networks"])
            expected = {"app": {"private", "documents"}, "ocr": {"documents"}, "proxy": {"private", "edge"}}[name]
            if networks != expected:
                raise ValueError()
            ports = service.get("ports", [])
            if name != "proxy" and ports:
                raise ValueError()
            if name == "proxy" and (len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1"
                    or str(ports[0].get("published")) != str(marker["port"]) or ports[0].get("target") != 443
                    or ports[0].get("protocol", "tcp") != "tcp"):
                raise ValueError()
        if any(model["networks"][network].get("internal") is not True for network in ("private", "documents")):
            raise ValueError()
        # A proxy connected exclusively to internal networks may be healthy but
        # unreachable on Docker's published host port. App/OCR cannot join edge.
        if model["networks"]["edge"].get("internal") is True:
            raise ValueError()
        app, ocr, proxy = (services[name] for name in ("app", "ocr", "proxy"))
        if app["image"] != marker["app_image"] or ocr["image"] != marker["ocr_image"]:
            raise ValueError()
        environment = app["environment"]
        expected_env = {"ADMIN_AGENT_CLIENT_ID": CLIENT_ID, "ADMIN_AGENT_PUBLIC_ORIGIN": marker["public_origin"],
                        "ADMIN_AGENT_DB": "/data/admin-agent.sqlite3", "ADMIN_AGENT_SESSION_SECRET_FILE": "/run/secrets/session_secret",
                        "ADMIN_AGENT_AI_ENABLED": "0", "ADMIN_AGENT_OCR_URL": "http://ocr:8766"}
        if any(str(environment.get(key)) != value for key, value in expected_env.items()):
            raise ValueError()
        if app["user"] != f"{config['uid']}:{config['gid']}" or ocr["user"] != "10002:10002":
            raise ValueError()
        if ocr.get("volumes") or ocr.get("secrets"):
            raise ValueError()
        app_mounts = {mount["target"]: mount for mount in app["volumes"]}
        if set(app_mounts) != {"/data"} or app_mounts["/data"].get("source") != str(directory / "data"):
            raise ValueError()
        if model["secrets"]["session_secret"]["file"] != str(directory / "secrets/session_secret"):
            raise ValueError()
        proxy_mounts = {mount["target"]: mount for mount in proxy["volumes"]}
        caddy = proxy_mounts["/etc/caddy/Caddyfile"]
        if caddy["source"] != str(ROOT / "deploy/Caddyfile.pilot") or caddy.get("read_only") is not True:
            raise ValueError()
    except (KeyError, ValueError, TypeError, IndexError):
        raise OpsError("La configuration Docker fusionnée ne respecte pas l'isolation locale du pilote ; aucun démarrage.") from None


def require_admin(config):
    if not Path(config["db"]).exists():
        raise OpsError("Créer un compte admin nominatif avec admin_agent.ops user-add avant up.")
    if any(Path(config["db"] + suffix).is_symlink() for suffix in ("", "-wal", "-shm", "-journal")):
        raise OpsError("La base du pilote et ses fichiers associés ne peuvent pas être des liens symboliques.")
    try:
        with _readonly_db(config["db"]) as connection:
            _identity(connection, CLIENT_ID)
            # Account schema is shared with the real production authentication layer.
            if not connection.execute("SELECT 1 FROM auth_users WHERE role='admin' AND enabled=1 LIMIT 1").fetchone():
                raise OpsError("Créer un compte admin nominatif avec admin_agent.ops user-add avant up.")
    except OpsError:
        raise
    except Exception as exc:
        raise OpsError("Base du pilote non initialisée ; créer un compte avec admin_agent.ops user-add avant up.") from exc
    finally:
        # A root CLI can create SQLite read-side WAL files; restore the app's
        # ownership just as the production account and connector CLIs do.
        _secure_db(config)


def export_certificate(directory, command):
    pem = run([*command, "exec", "-T", "proxy", "cat", "/data/caddy/pki/authorities/local/root.crt"]) + "\n"
    if "PRIVATE KEY" in pem or len(pem) > 20000:
        raise OpsError("Le certificat public attendu n'est pas valide.")
    try:
        der = ssl.PEM_cert_to_DER_cert(pem)
    except (ValueError, TypeError) as exc:
        raise OpsError("Le certificat public attendu n'est pas valide.") from exc
    target = directory / "tls/pilot-root-ca.crt"
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise OpsError("Répertoire de certificat invalide.")
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.read_text() != pem:
            raise OpsError("Un autre certificat existe ; vérifier la rotation de l'autorité avant de le remplacer.")
    else:
        _private_write(target, pem)
    return {"certificate": str(target), "sha256_der": hashlib.sha256(der).hexdigest(), "trust_installed": False,
            "instruction": "Importer uniquement ce certificat public dans le navigateur de recette après vérification de son empreinte."}


def execute(action, directory, no_build=False):
    directory = private_directory(directory)
    marker, config = load_pilot(directory)
    check_compose()
    command = compose_command(directory, marker)
    try:
        model = json.loads(run([*command, "config", "--format", "json"]))
    except ValueError as exc:
        raise OpsError("Docker Compose n'a pas retourné une configuration JSON valide.") from exc
    validate_compose(model, directory, marker, config)
    if action == "config":
        return {"valid": True, "name": marker["project"], "url": marker["public_origin"], "loopback_only": True}
    if action == "up":
        require_admin(config)
        if not no_build:
            run([*command, "build", "--pull"], capture=False)
        run([*command, "up", "-d", "--wait", "--wait-timeout", "180", "--no-build"], capture=False)
        return {"started": True, "url": marker["public_origin"], "synthetic_only": True,
                "next_step": "Exporter le certificat avec certificate ; installer sa confiance dans le navigateur de recette."}
    if action == "stop":
        run([*command, "stop"], capture=False)
        return {"stopped": True, "data_deleted": False, "certificates_deleted": False}
    if action == "status":
        result = run([*command, "ps", "--format", "json"])
        records = json.loads(result) if result.startswith("[") else [json.loads(line) for line in result.splitlines() if line]
        return {"url": marker["public_origin"], "services": [{key: item.get(key) for key in ("Service", "State", "Health")} for item in records]}
    if action == "certificate":
        return export_certificate(directory, command)
    raise OpsError("Action inconnue.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("init", "up", "status", "stop", "certificate", "config"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
        if name == "init":
            command.add_argument("--port", type=int, default=8443)
            command.add_argument("--app-image", default="admin-agent:pilot-local")
            command.add_argument("--ocr-image", default="admin-agent-ocr:pilot-local")
        if name == "up":
            command.add_argument("--no-build", action="store_true")
    args = parser.parse_args(argv)
    try:
        if os.name != "posix":
            raise OpsError("Ce pilote utilise les permissions Linux ; exécuter depuis Linux ou WSL2.")
        result = (initialize(args.directory, args.port, args.app_image, args.ocr_image) if args.action == "init"
                  else execute(args.action, args.directory, getattr(args, "no_build", False)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OpsError, OSError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, OpsError) else "Opération locale impossible ; vérifier les permissions et Docker."
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
