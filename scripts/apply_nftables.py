#!/usr/bin/env python3
"""Apply the DMZ WebUI nftables tables without touching foreign tables."""

from __future__ import annotations

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from firewall import apply_owned_rules  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="/etc/nftables.conf",
        help="DMZ WebUI nftables config path",
    )
    parser.add_argument(
        "--migrate-legacy",
        action="store_true",
        help="remove only recognized DMZ WebUI legacy chains after applying owned tables",
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("Error: this script must be run as root", file=sys.stderr)
        return 1

    try:
        with open(args.config, "r", encoding="utf-8") as config_file:
            config_text = config_file.read()
        apply_owned_rules(config_text, migrate_legacy=args.migrate_legacy)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print("Applied DMZ WebUI nftables tables without reloading the global ruleset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
