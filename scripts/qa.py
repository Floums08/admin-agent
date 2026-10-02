"""Repeatable offline QA gate; no network access or external accounts required."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_catalog():
    catalog = json.loads((ROOT / "data/skills.json").read_text())
    ids = set()
    for skill in catalog["skills"]:
        identifier = skill["id"]
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier), identifier
        assert identifier not in ids, f"Duplicate skill: {identifier}"
        ids.add(identifier)
        path = (ROOT / skill["path"]).resolve()
        assert path.is_relative_to(ROOT / "skills"), f"Unsafe skill path: {path}"
        body = path.read_text()
        assert body.startswith("---\n"), f"Missing frontmatter: {identifier}"
        metadata = body.split("---", 2)[1]
        assert f"name: {identifier}" in metadata, f"Name mismatch: {identifier}"
        assert "description:" in metadata, f"Missing description: {identifier}"
        assert "TODO" not in body and len(body.splitlines()) < 500, identifier
        assert skill["status"] in ("implemented", "guided"), identifier
        assert skill["priority"] in ("P0", "P1", "P2"), identifier
    assert len(ids) == 12, f"Expected 12 skills, got {len(ids)}"
    print(f"Catalog: {len(ids)} skills checked", flush=True)


def main():
    validate_catalog()
    for filename in ("index.html", "styles.css", "app.js"):
        path = ROOT / "web" / filename
        assert path.is_file() and path.stat().st_size > 0, f"Missing frontend asset: {filename}"
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=True)
    node = shutil.which("node")
    if node:
        for path in (ROOT / "web").glob("*.js"):
            subprocess.run([node, "--check", str(path)], check=True)
        print("Frontend JavaScript syntax: checked", flush=True)
    else:
        print("Frontend syntax: skipped (Node unavailable); Python gate completed.", flush=True)
    print("Offline QA gate passed. No live LLM or external connector certified.", flush=True)


if __name__ == "__main__":
    main()
