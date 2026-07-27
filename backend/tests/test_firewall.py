import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

import firewall


VALID_CONFIG = """#!/usr/sbin/nft -f

table inet dmz_webui_filter {
    chain input {
        type filter hook input priority filter; policy drop;
    }
}

table ip dmz_webui_nat {
    set cn_ipv4 {
        type ipv4_addr
        flags interval
        elements = { 10.0.0.0/8 }
    }
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept
    }
}
"""


class ExtractOwnedTablesTests(unittest.TestCase):
    def test_accepts_exact_owned_tables(self):
        extracted = firewall.extract_owned_tables(VALID_CONFIG)

        self.assertIn("table inet dmz_webui_filter", extracted)
        self.assertIn("table ip dmz_webui_nat", extracted)

    def test_rejects_foreign_table(self):
        config = VALID_CONFIG + "\ntable ip docker_sentinel { chain keep {} }\n"

        with self.assertRaisesRegex(
            firewall.FirewallConfigError, "non-DMZ table"
        ):
            firewall.extract_owned_tables(config)

    def test_rejects_global_flush(self):
        config = "flush ruleset\n" + VALID_CONFIG

        with self.assertRaisesRegex(
            firewall.FirewallConfigError, "Unsupported top-level"
        ):
            firewall.extract_owned_tables(config)

    def test_requires_both_owned_tables(self):
        config = VALID_CONFIG.split("table ip dmz_webui_nat", 1)[0]

        with self.assertRaisesRegex(
            firewall.FirewallConfigError, "Missing DMZ WebUI table"
        ):
            firewall.extract_owned_tables(config)

    def test_nested_set_replacement_does_not_consume_following_chain(self):
        replacement = """    set cn_ipv4 {
        type ipv4_addr
        flags interval
        elements = { 192.0.2.0/24 }
    }"""

        updated = firewall.replace_named_block(
            VALID_CONFIG, "set cn_ipv4", replacement
        )

        self.assertIn("elements = { 192.0.2.0/24 }", updated)
        self.assertIn("chain prerouting", updated)
        self.assertEqual(updated.count("set cn_ipv4"), 1)


class OwnedApplyBatchTests(unittest.TestCase):
    @patch("firewall._nft_object_exists", side_effect=[True, False])
    def test_replace_batch_mentions_only_owned_tables(self, _exists):
        batch = firewall.build_owned_replace_batch(VALID_CONFIG)

        self.assertIn("delete table inet dmz_webui_filter", batch)
        self.assertNotIn("delete table ip dmz_webui_nat", batch)
        self.assertNotIn("DOCKER", batch)
        self.assertNotIn("docker_sentinel", batch)
        self.assertNotIn("flush ruleset", batch)

    @patch("firewall._run_nft")
    @patch("firewall.build_owned_replace_batch", return_value="owned batch\n")
    def test_apply_checks_then_executes_the_same_atomic_batch(
        self, _build_batch, run_nft
    ):
        run_nft.return_value = subprocess.CompletedProcess([], 0, "", "")

        firewall.apply_owned_rules(VALID_CONFIG)

        self.assertEqual(run_nft.call_count, 2)
        self.assertEqual(
            run_nft.call_args_list[0].args[0], ["-c", "-f", "-"]
        )
        self.assertEqual(
            run_nft.call_args_list[1].args[0], ["-f", "-"]
        )
        self.assertEqual(
            run_nft.call_args_list[0].kwargs["input_text"], "owned batch\n"
        )
        self.assertEqual(
            run_nft.call_args_list[1].kwargs["input_text"], "owned batch\n"
        )

    @patch("firewall._execute_checked_batch")
    @patch("firewall._nft_object_exists", return_value=False)
    def test_apply_replaces_only_the_changed_nat_table(self, _exists, execute):
        updated = VALID_CONFIG.replace(
            "policy accept\n    }",
            "policy accept\n        tcp dport 8080 dnat to 10.0.0.10:80\n    }",
        )

        firewall.apply_owned_rules(
            updated,
            previous_config_text=VALID_CONFIG,
        )

        batch = execute.call_args.args[0]
        self.assertIn("table ip dmz_webui_nat", batch)
        self.assertNotIn("table inet dmz_webui_filter", batch)

    @patch("firewall._execute_checked_batch")
    def test_identical_config_does_not_reload_any_table(self, execute):
        firewall.apply_owned_rules(
            VALID_CONFIG,
            previous_config_text=VALID_CONFIG,
        )

        execute.assert_not_called()


class LegacyCleanupTests(unittest.TestCase):
    @patch("firewall._nft_object_exists")
    def test_cleanup_is_guarded_by_project_marker_sets(self, exists):
        present = {
            ("set", "inet", "filter", "ssh_ports"),
            ("chain", "inet", "filter", "input"),
            ("chain", "inet", "filter", "output"),
            ("chain", "ip", "nat", "DOCKER"),
        }
        exists.side_effect = lambda arguments: tuple(arguments) in present

        batch = firewall.build_legacy_cleanup_batch()

        self.assertIn("flush chain inet filter input", batch)
        self.assertIn("delete chain inet filter output", batch)
        self.assertIn("delete set inet filter ssh_ports", batch)
        self.assertNotIn("forward", batch)
        self.assertNotIn("ip nat", batch)
        self.assertNotIn("DOCKER", batch)

    @patch("firewall._nft_object_exists", return_value=False)
    def test_cleanup_does_nothing_without_project_markers(self, _exists):
        self.assertEqual(firewall.build_legacy_cleanup_batch(), "")


class RepositoryConfigTests(unittest.TestCase):
    def test_repository_config_has_strict_ownership_boundary(self):
        config = (PROJECT_ROOT / "configs" / "nftables.conf").read_text()

        self.assertNotIn("flush ruleset", config)
        extracted = firewall.extract_owned_tables(config)
        self.assertEqual(extracted.count("table "), 2)


if __name__ == "__main__":
    unittest.main()
