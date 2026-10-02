"""Run with python3 -m admin_agent --port 8765."""

import argparse
from .server import serve


def main():
    parser = argparse.ArgumentParser(description="Pilote administratif local avec relecture humaine.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    parser.add_argument("--db", default=None, help="Chemin du fichier SQLite local")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port doit être compris entre 0 et 65535")
    serve(port=args.port, db_path=args.db, host=args.host)


if __name__ == "__main__":
    main()
