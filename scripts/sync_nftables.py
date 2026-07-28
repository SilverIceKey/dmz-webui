#!/usr/bin/env python3
"""
Sync project nftables base config with runtime /etc/nftables.conf.

Usage: sudo python3 scripts/sync_nftables.py

Preserves:
- SSL proxy rules from /etc/dmz-webui/ssl_proxy_rules.json
- User-added DNAT rules not present in the project base config
- Existing cn_ipv4 set content if it has elements
"""
import json
import os
import re
import shutil
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from firewall import (  # noqa: E402
    extract_named_block,
    insert_lines_before_named_block_close,
    upsert_named_block_in_parent,
)

PROJECT_NFT = "/opt/dmz-webui/configs/nftables.conf"
RUNTIME_NFT = "/etc/nftables.conf"
SSL_PROXY_RULES = "/etc/dmz-webui/ssl_proxy_rules.json"


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


_DNAT_RE = re.compile(
    r"^\s*(?:(ip\s+saddr\s+(?:!=\s+)?(?:@cn_ipv4|\{[^}]*\})\s+))?"
    r"(tcp|udp)\s+dport\s+(\d+)\s+dnat\s+to\s+([0-9.]+):(\d+)"
    r"(?:\s*#\s*(.*))?",
    re.MULTILINE,
)


def parse_dnat_rules(text: str):
    rules = []
    for m in _DNAT_RE.finditer(text):
        rules.append({
            "prefix": (m.group(1) or "").strip(),
            "proto": m.group(2),
            "port": int(m.group(3)),
            "dest_ip": m.group(4),
            "dest_port": int(m.group(5)),
            "comment": m.group(6).strip() if m.group(6) else "",
        })
    return rules


def rule_key(r: dict):
    return (r["proto"], r["port"], r["dest_ip"], r["dest_port"])


def insert_before_chain_close(text: str, chain_name: str, lines: list[str]) -> str:
    return insert_lines_before_named_block_close(
        text, f"chain {chain_name}", lines
    )


def extract_cn_ipv4_set(text: str) -> str | None:
    """Return the existing cn_ipv4 set block if it contains elements, else None."""
    match = re.search(
        r"set\s+cn_ipv4\s*\{[^}]+flags\s+interval[^}]*elements\s*=\s*\{([^}]*)\}\s*\}",
        text,
        re.DOTALL,
    )
    if not match:
        return None
    elements = match.group(1).strip()
    if not elements:
        return None
    return f"""    set cn_ipv4 {{
        type ipv4_addr
        flags interval
        elements = {{ {elements} }}
    }}"""


def sync_cn_ipv4_sets(text: str, set_block: str | None) -> str:
    if set_block is None:
        return text
    text = upsert_named_block_in_parent(
        text,
        "table inet dmz_webui_filter",
        "set cn_ipv4",
        set_block,
        "chain input",
    )
    return upsert_named_block_in_parent(
        text,
        "table ip dmz_webui_nat",
        "set cn_ipv4",
        set_block,
        "chain prerouting",
    )


def main():
    if os.geteuid() != 0:
        print("Error: this script must be run as root", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(PROJECT_NFT):
        print(f"Error: project nftables config not found: {PROJECT_NFT}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(RUNTIME_NFT):
        print(f"Warning: runtime nftables config not found, creating: {RUNTIME_NFT}", file=sys.stderr)

    # Backup current runtime config
    if os.path.exists(RUNTIME_NFT):
        backup = f"{RUNTIME_NFT}.backup.{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(RUNTIME_NFT, backup)
        print(f"Backed up {RUNTIME_NFT} -> {backup}")
        runtime_text = read(RUNTIME_NFT)
    else:
        runtime_text = ""

    base_text = read(PROJECT_NFT)

    # Preserve cn_ipv4 set from runtime if populated
    cn_set_block = extract_cn_ipv4_set(runtime_text)
    if cn_set_block:
        base_text = sync_cn_ipv4_sets(base_text, cn_set_block)
        print("Preserved existing cn_ipv4 sets")

    # Identify project base DNAT rules
    base_prerouting = extract_named_block(base_text, "chain prerouting") or ""
    base_rules = parse_dnat_rules(base_prerouting)
    base_keys = {rule_key(r) for r in base_rules}

    # Identify user-added DNAT rules in runtime that are not in base and not ssl-proxy managed
    runtime_prerouting = extract_named_block(runtime_text, "chain prerouting") or ""
    runtime_rules = parse_dnat_rules(runtime_prerouting)
    extra_rules = [
        r for r in runtime_rules
        if rule_key(r) not in base_keys and not r["comment"].startswith("ssl-proxy")
    ]

    extra_lines = []
    for r in extra_rules:
        prefix = f"{r['prefix']} " if r["prefix"] else ""
        line = f"        {prefix}{r['proto']} dport {r['port']} dnat to {r['dest_ip']}:{r['dest_port']}"
        if r["comment"]:
            line += f" # {r['comment']}"
        extra_lines.append(line)

    if extra_lines:
        base_text = insert_before_chain_close(base_text, "prerouting", extra_lines)
        print(f"Preserved {len(extra_lines)} user-added DNAT rule(s)")

    runtime_input = extract_named_block(runtime_text, "chain input") or ""
    local_open_lines = [
        line
        for line in runtime_input.splitlines()
        if re.search(r"#\s*local-open(?::.*)?\s*$", line)
    ]
    if local_open_lines:
        base_text = insert_before_chain_close(
            base_text, "input", local_open_lines
        )
        print(f"Preserved {len(local_open_lines)} local port rule(s)")

    # Load SSL proxy rules and re-apply them
    ssl_rules = []
    if os.path.exists(SSL_PROXY_RULES):
        try:
            with open(SSL_PROXY_RULES, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    ssl_rules = data
        except Exception as e:
            print(f"Warning: failed to load SSL proxy rules: {e}", file=sys.stderr)

    input_lines = []
    prerouting_lines = []
    for rule in ssl_rules:
        port = rule["port"]
        suffix = f"  # ssl-proxy:{port}"
        input_lines.append(f"        tcp dport {port} accept{suffix}")
        if not rule.get("ssl_enabled", True):
            prerouting_lines.append(
                f"        tcp dport {port} dnat to {rule['dest_ip']}:{rule['dest_port']}{suffix}"
            )

    if input_lines:
        base_text = insert_before_chain_close(base_text, "input", input_lines)
        print(f"Applied {len(input_lines)} SSL proxy input rule(s)")

    if prerouting_lines:
        base_text = insert_before_chain_close(base_text, "prerouting", prerouting_lines)
        print(f"Applied {len(prerouting_lines)} SSL proxy prerouting rule(s)")

    write(RUNTIME_NFT, base_text)
    print(f"Updated {RUNTIME_NFT}")


if __name__ == "__main__":
    main()
