#!/usr/bin/env python3
"""Generate, validate, and atomically install the complete DMZ Caddyfile."""

from __future__ import annotations

import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import _build_caddyfile, _validate_caddy, _write_caddy  # noqa: E402


def main() -> None:
    content = _build_caddyfile()
    _validate_caddy(content)
    _write_caddy(content)
    print("Generated and validated complete Caddyfile")


if __name__ == "__main__":
    main()
