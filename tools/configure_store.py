#!/usr/bin/env python3
"""Prepare the Umbrel package for a real GitHub owner and app version.

The only values that cannot be known before the repository exists are the
GitHub owner (used by the raw icon/gallery URLs and the GHCR image) and the
version tag. This script rewrites them consistently in the manifest and the
Umbrel compose file.

Usage: python3 tools/configure_store.py <github-owner> [version]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "frabot-frabot" / "umbrel-app.yml"
COMPOSE = ROOT / "frabot-frabot" / "docker-compose.yml"

OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip())
        return 2
    owner = sys.argv[1].strip().lower()
    version = sys.argv[2].strip() if len(sys.argv) == 3 else None

    if not OWNER_RE.fullmatch(owner):
        print(f"Owner GitHub non valido: {owner!r}", file=sys.stderr)
        return 2
    if version is not None and not VERSION_RE.fullmatch(version):
        print(f"Versione non valida: {version!r} (usa per esempio 1.0.1)", file=sys.stderr)
        return 2

    manifest = MANIFEST.read_text(encoding="utf-8").replace("OWNER", owner)
    compose = COMPOSE.read_text(encoding="utf-8").replace("OWNER", owner)

    if version:
        manifest, count = re.subn(
            r'(?m)^version: "[^"]*"$', f'version: "{version}"', manifest, count=1
        )
        if count != 1:
            print("Campo version non trovato nel manifest.", file=sys.stderr)
            return 1
        compose, count = re.subn(
            r"(?m)^(\s*image: ghcr\.io/[^:\s]+:)[^\s]+$",
            rf"\g<1>{version}",
            compose,
            count=1,
        )
        if count != 1:
            print("Immagine GHCR non trovata nel compose.", file=sys.stderr)
            return 1

    MANIFEST.write_text(manifest, encoding="utf-8")
    COMPOSE.write_text(compose, encoding="utf-8")
    print(f"Store configurato per github.com/{owner}/frabot" + (f", versione {version}" if version else ""))
    print("Ora pubblica il repository e avvia il workflow 'Publish Docker image'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
