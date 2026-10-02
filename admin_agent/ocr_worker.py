"""Private-network WSGI OCR worker. Never expose this service publicly."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading

from .ocr import (LANGUAGES, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, MEDIA_TYPES,
                  OCRError, TOOLS, WALL_SECONDS)

_BUSY = threading.BoundedSemaphore(1)


def _isolated_extract(data, media, language, force):
    """Separate process: Pillow decoding also has a hard wall/CPU/memory limit."""
    command = [sys.executable, "-m", "admin_agent.ocr", "--worker-child", media, language, "1" if force else "0"]
    if sys.platform.startswith("linux"):
        if not TOOLS["prlimit"].is_file():
            raise OCRError("ocr_unavailable", "Les limites de processus OCR sont indisponibles.", 503)
        command = [str(TOOLS["prlimit"]), "--as=1073741824", "--cpu=55", "--fsize=33554432", "--nofile=64", "--nproc=64", "--", *command]
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "OMP_THREAD_LIMIT": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.environ.get("ADMIN_AGENT_OCR_TESSDATA_DIR"):
        env["ADMIN_AGENT_OCR_TESSDATA_DIR"] = os.environ["ADMIN_AGENT_OCR_TESSDATA_DIR"]
    with tempfile.TemporaryDirectory(prefix="admin-ocr-worker-") as temp:
        env["TMPDIR"] = temp
        output = Path(temp) / "result.json"
        try:
            with output.open("wb") as stream:
                process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                           stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.DEVNULL,
                                           start_new_session=True)
                try:
                    process.communicate(input=data, timeout=WALL_SECONDS)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5)
                    raise OCRError("ocr_timeout", "Le délai maximal d'extraction est dépassé.", 504) from None
            if process.returncode != 0 or not 0 < output.stat().st_size <= MAX_OUTPUT_BYTES:
                raise OCRError("ocr_failed", "Extraction indisponible ; vérifier les limites du document.", 422)
            payload = json.loads(output.read_bytes())
            if payload.get("status") != 200:
                error = payload.get("error", {})
                raise OCRError(error.get("code", "ocr_failed"), error.get("message", "Extraction indisponible."), payload.get("status", 500))
            return payload["result"]
        except (OSError, ValueError, KeyError):
            raise OCRError("ocr_failed", "Extraction indisponible.", 503) from None


def application(environ, start_response):
    status = 200
    headers = [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")]
    try:
        method, path = environ.get("REQUEST_METHOD"), environ.get("PATH_INFO")
        if method == "GET" and path == "/health":
            result = {"status": "ok", "service": "ocr-worker", "version": 1}
        elif method == "POST" and path == "/extract":
            raw_length = environ.get("CONTENT_LENGTH", "")
            if not raw_length.isascii() or not raw_length.isdecimal():
                raise OCRError("length_required", "Une taille de document explicite est requise.", 411)
            length = int(raw_length)
            if not 0 < length <= MAX_INPUT_BYTES:
                raise OCRError("document_too_large", "Le document doit être non vide et inférieur à 5 Mio.", 413)
            media = environ.get("CONTENT_TYPE", "")
            language = environ.get("HTTP_X_OCR_LANGUAGE", "fra+spa+eng")
            force = environ.get("HTTP_X_OCR_FORCE", "0")
            if media not in MEDIA_TYPES or language not in LANGUAGES or force not in ("0", "1"):
                raise OCRError("invalid_options", "Les options d'extraction sont invalides.", 400)
            if not _BUSY.acquire(blocking=False):
                raise OCRError("ocr_busy", "Une extraction est déjà en cours ; réessayer plus tard.", 503)
            try:
                data = environ["wsgi.input"].read(length)
                if len(data) != length:
                    raise OCRError("incomplete_document", "Le transfert du document est incomplet.", 400)
                result = _isolated_extract(data, media, language, force == "1")
            finally:
                _BUSY.release()
        else:
            raise OCRError("not_found", "Ressource indisponible.", 404)
        body = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_OUTPUT_BYTES:
            raise OCRError("extraction_too_large", "La sortie d'extraction dépasse la limite autorisée.")
    except OCRError as exc:
        status = exc.status
        body = json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False).encode("utf-8")
    except Exception:
        status = 500
        body = b'{"error":{"code":"ocr_failed","message":"Extraction indisponible."}}'
    headers.append(("Content-Length", str(len(body))))
    labels = {200: "OK", 400: "Bad Request", 404: "Not Found", 411: "Length Required", 413: "Content Too Large", 415: "Unsupported Media Type", 422: "Unprocessable Content", 500: "Internal Server Error", 503: "Service Unavailable", 504: "Gateway Timeout"}
    start_response(f"{status} {labels.get(status, 'Error')}", headers)
    return [body]


def main():
    parser = argparse.ArgumentParser(description="Isolated private-network OCR worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    from waitress import serve
    serve(application, host=args.host, port=args.port, threads=2, connection_limit=8,
          max_request_body_size=MAX_INPUT_BYTES, max_request_header_size=8192,
          channel_timeout=70, ident="admin-ocr")


if __name__ == "__main__":
    main()
