import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "sync_nftables", PROJECT_ROOT / "scripts" / "sync_nftables.py"
)
sync_nftables = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sync_nftables)


OLD_RUNTIME_CONFIG = """#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    set ssh_ports { type inet_service; elements = { 22 } }
    chain input {
        type filter hook input priority filter; policy drop;
        ip saddr @cn_ipv4 tcp dport 19262 accept # local-open:Portainer
    }
}

table ip nat {
    set cn_ipv4 {
        type ipv4_addr
        flags interval
        elements = { 192.0.2.0/24 }
    }
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept
        tcp dport 1000 dnat to 10.0.0.10:80 # user-rule
        tcp dport 2000 dnat to 10.0.0.20:443 # ssl-proxy:2000
    }
    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept
    }
    chain DOCKER {
        tcp dport 3000 dnat to 172.17.0.2:3000
    }
}
"""


class SyncMigrationTests(unittest.TestCase):
    def test_inserted_rule_does_not_attach_to_chain_closing_brace(self):
        config = (PROJECT_ROOT / "configs" / "nftables.conf").read_text()
        line = (
            "        ip saddr @cn_ipv4 tcp dport 19262 "
            "dnat to 127.0.0.1:19262 # Portainer"
        )

        updated = sync_nftables.insert_before_chain_close(
            config, "prerouting", [line]
        )

        self.assertIn(f"{line}\n    }}", updated)
        self.assertNotIn(f"{line}}}", updated)

    def test_sync_migrates_project_data_without_copying_docker_chain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_config = root / "project.nft"
            runtime_config = root / "runtime.nft"
            ssl_rules = root / "ssl.json"
            project_config.write_text(
                (PROJECT_ROOT / "configs" / "nftables.conf").read_text()
                .replace("<SSH_PORT>", "22")
                .replace("<WAN_INTERFACE>", "eth0")
            )
            runtime_config.write_text(OLD_RUNTIME_CONFIG)
            ssl_rules.write_text(json.dumps([{
                "id": 1,
                "port": 2000,
                "dest_ip": "10.0.0.20",
                "dest_port": 443,
                "ssl_enabled": False,
            }]))

            with (
                patch.object(sync_nftables, "PROJECT_NFT", str(project_config)),
                patch.object(sync_nftables, "RUNTIME_NFT", str(runtime_config)),
                patch.object(sync_nftables, "SSL_PROXY_RULES", str(ssl_rules)),
                patch.object(sync_nftables.os, "geteuid", return_value=0),
            ):
                sync_nftables.main()

            migrated = runtime_config.read_text()
            self.assertNotIn("flush ruleset", migrated)
            self.assertIn("table inet dmz_webui_filter", migrated)
            self.assertIn("table ip dmz_webui_nat", migrated)
            self.assertIn("elements = { 192.0.2.0/24 }", migrated)
            self.assertEqual(
                migrated.count("elements = { 192.0.2.0/24 }"),
                2,
            )
            self.assertIn(
                "tcp dport 1000 dnat to 10.0.0.10:80 # user-rule", migrated
            )
            self.assertEqual(migrated.count("ssl-proxy:2000"), 2)
            self.assertIn(
                "ip saddr @cn_ipv4 tcp dport 19262 accept "
                "# local-open:Portainer",
                migrated,
            )
            self.assertNotIn("chain DOCKER", migrated)
            self.assertNotIn("172.17.0.2:3000", migrated)


if __name__ == "__main__":
    unittest.main()
