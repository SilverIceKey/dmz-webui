import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import call, patch

from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

if "pam" not in sys.modules:
    fake_pam = types.ModuleType("pam")
    fake_pam.pam = object
    sys.modules["pam"] = fake_pam

import main
from firewall import extract_named_block


OLD_RULES = [{
    "id": 1,
    "port": 9443,
    "dest_ip": "10.0.0.10",
    "dest_port": 443,
    "ssl_enabled": True,
    "comment": "old",
}]
NEW_RULES = [{
    "id": 2,
    "port": 9553,
    "dest_ip": "10.0.0.20",
    "dest_port": 443,
    "ssl_enabled": True,
    "comment": "new",
}]


class SslProxyTransactionTests(unittest.TestCase):
    def transaction_patches(self):
        return (
            patch.object(main, "_load_ssl_proxy_rules", return_value=OLD_RULES),
            patch.object(main, "_read_caddy", return_value="old caddy"),
            patch.object(main, "_read_nftables", return_value="old nftables"),
            patch.object(main, "_build_caddyfile", return_value="new caddy"),
            patch.object(main, "_build_ssl_proxy_nftables", return_value="new nftables"),
            patch.object(main, "_validate_caddy"),
            patch.object(main, "_write_caddy"),
            patch.object(main, "_reload_caddy"),
            patch.object(main, "_commit_nftables"),
            patch.object(main, "_save_ssl_proxy_rules"),
        )

    def test_success_saves_rules_only_after_runtime_apply(self):
        patches = self.transaction_patches()
        mocks = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        _, _, _, _, _, validate, write_caddy, reload_caddy, commit_nft, save_rules = mocks

        main._apply_ssl_proxy_rules(NEW_RULES)

        validate.assert_called_once_with("new caddy")
        write_caddy.assert_called_once_with("new caddy")
        reload_caddy.assert_called_once_with()
        commit_nft.assert_called_once_with("new nftables")
        save_rules.assert_called_once_with(NEW_RULES)

    def test_caddy_reload_failure_restores_old_files_and_rules(self):
        patches = self.transaction_patches()
        mocks = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        _, _, _, _, _, _, write_caddy, reload_caddy, commit_nft, save_rules = mocks
        reload_caddy.side_effect = [RuntimeError("reload failed"), None]

        with self.assertRaisesRegex(RuntimeError, "reload failed"):
            main._apply_ssl_proxy_rules(NEW_RULES)

        self.assertEqual(write_caddy.call_args_list, [call("new caddy"), call("old caddy")])
        self.assertEqual(reload_caddy.call_count, 2)
        commit_nft.assert_not_called()
        save_rules.assert_called_once_with(OLD_RULES)

    def test_json_write_failure_rolls_back_caddy_and_nftables(self):
        patches = self.transaction_patches()
        mocks = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        _, _, _, _, _, _, write_caddy, reload_caddy, commit_nft, save_rules = mocks
        save_rules.side_effect = [OSError("disk full"), None]

        with self.assertRaisesRegex(OSError, "disk full"):
            main._apply_ssl_proxy_rules(NEW_RULES)

        self.assertEqual(
            commit_nft.call_args_list,
            [call("new nftables"), call("old nftables")],
        )
        self.assertEqual(write_caddy.call_args_list, [call("new caddy"), call("old caddy")])
        self.assertEqual(reload_caddy.call_count, 2)
        self.assertEqual(save_rules.call_args_list, [call(NEW_RULES), call(OLD_RULES)])

    def test_non_ssl_forwarding_does_not_open_the_input_chain(self):
        config = (BACKEND_DIR.parent / "configs" / "nftables.conf").read_text()
        rule = [{
            "id": 3,
            "port": 9663,
            "dest_ip": "10.0.0.30",
            "dest_port": 443,
            "ssl_enabled": False,
            "comment": "plain forwarding",
        }]

        with patch.object(main, "_read_nftables", return_value=config):
            updated = main._build_ssl_proxy_nftables(rule)

        input_chain = extract_named_block(updated, "chain input")
        prerouting_chain = extract_named_block(updated, "chain prerouting")
        self.assertIsNotNone(input_chain)
        self.assertIsNotNone(prerouting_chain)
        self.assertNotIn("ssl-proxy:9663", input_chain)
        self.assertIn("ssl-proxy:9663", prerouting_chain)


class CaddyReloadTests(unittest.TestCase):
    @patch.object(main.subprocess, "run")
    def test_reload_never_falls_back_to_restart(self, run):
        run.side_effect = subprocess.CalledProcessError(1, ["systemctl", "reload", "caddy"])

        with self.assertRaises(subprocess.CalledProcessError):
            main._reload_caddy()

        run.assert_called_once_with(["systemctl", "reload", "caddy"], check=True)


class EndpointMutationTests(unittest.TestCase):
    def test_title_environment_uses_safe_default(self):
        with patch.dict(main.os.environ, {
            "DMZ_SITE_TITLE": "  银钥管理  ",
            "DMZ_TAB_TITLE": "bad\nvalue",
        }):
            self.assertEqual(
                main._configured_title("DMZ_SITE_TITLE"),
                "银钥管理",
            )
            self.assertEqual(
                main._configured_title("DMZ_TAB_TITLE"),
                "DMZ WebUI",
            )

    def test_public_config_exposes_branding_without_auth(self):
        with (
            patch.object(main, "DMZ_ICP_NUMBER", "浙ICP备12345678号"),
            patch.object(main, "DMZ_SITE_TITLE", "银钥管理"),
            patch.object(main, "DMZ_TAB_TITLE", "银钥控制台"),
        ):
            result = main.get_public_config()

        self.assertEqual(result, {
            "icp_number": "浙ICP备12345678号",
            "site_title": "银钥管理",
            "tab_title": "银钥控制台",
        })
        route = next(route for route in main.app.routes if route.path == "/api/public-config")
        self.assertEqual(route.dependant.dependencies, [])

    @patch.object(main, "_apply_ssl_proxy_rules", side_effect=RuntimeError("apply failed"))
    @patch.object(main, "_load_ssl_proxy_rules", return_value=[])
    def test_ssl_create_failure_reports_rollback(self, _load, _apply):
        rule = main.SslProxyRuleCreate(
            port=9443,
            dest_ip="10.0.0.10",
            dest_port=443,
            ssl_enabled=True,
            comment="test",
        )

        with patch.object(main, "_check_port_conflict"):
            with self.assertRaises(HTTPException) as raised:
                main.create_ssl_proxy_rule(rule, "tester")

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("previous configuration restored", raised.exception.detail)

    @patch.object(main, "_commit_nftables")
    @patch.object(main, "_add_nft_rule", return_value="new nftables")
    @patch.object(main, "_read_nftables", return_value="old nftables")
    def test_nft_create_returns_success_after_commit(self, _read, _add, commit):
        rule = main.NfRuleCreate(
            port=8080,
            protocol="tcp",
            dest_ip="10.0.0.10",
            dest_port=80,
        )

        result = main.create_nft_rule(rule, "tester")

        commit.assert_called_once_with("new nftables")
        self.assertEqual(result, {"ok": True})

    def test_nft_edit_repairs_legacy_rule_attached_to_closing_brace(self):
        config = (BACKEND_DIR.parent / "configs" / "nftables.conf").read_text()
        malformed = config.replace(
            "\n    chain postrouting {",
            "\n"
            "        ip saddr @cn_ipv4 tcp dport 19262 "
            "dnat to 127.0.0.1:19262 # Portainer}\n"
            "\n    chain postrouting {",
        ).replace(
            "\n    }\n\n"
            "        ip saddr @cn_ipv4 tcp dport 19262",
            "\n"
            "        ip saddr @cn_ipv4 tcp dport 19262",
            1,
        )
        replacement = main.NfRuleCreate(
            port=19262,
            protocol="tcp",
            dest_ip="127.0.0.1",
            dest_port=19262,
            whitelist_type="cn",
            comment="Portainer updated",
        )

        removed = main._remove_nft_rule(
            malformed, 19262, "tcp", "127.0.0.1", 19262
        )
        updated = main._add_nft_rule(removed, replacement)

        self.assertIn("# Portainer updated\n    }", updated)
        self.assertNotIn("# Portainer updated}", updated)
        self.assertIsNotNone(extract_named_block(updated, "chain prerouting"))

    def test_local_open_rule_round_trip_preserves_fixed_input_rules(self):
        config = (BACKEND_DIR.parent / "configs" / "nftables.conf").read_text()
        rule = main.LocalPortRuleCreate(
            port=19262,
            protocol="both",
            whitelist_type="cn",
            comment="Portainer",
        )

        added = main._add_local_port_rule(config, rule)
        parsed = main._parse_local_port_rules(added)
        removed = main._remove_local_port_rule(added, 19262, "both")

        self.assertIn(
            "ip saddr @cn_ipv4 tcp dport 19262 accept # local-open:Portainer",
            added,
        )
        self.assertIn(
            "ip saddr @cn_ipv4 udp dport 19262 accept # local-open:Portainer",
            added,
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].protocol, "both")
        self.assertEqual(parsed[0].whitelist_type, "cn")
        self.assertEqual(parsed[0].comment, "Portainer")
        self.assertNotIn("local-open", removed)
        self.assertIn("tcp dport @ssh_ports accept", removed)
        self.assertIn("tcp dport 5000 accept", removed)
        self.assertIn("tcp dport 8443 accept", removed)

    def test_local_open_validates_custom_ipv4_whitelist_and_comment(self):
        valid = main.LocalPortRuleCreate(
            port=19262,
            protocol="tcp",
            whitelist_type="custom",
            whitelist_ips="192.0.2.1, 198.51.100.0/24",
        )
        self.assertEqual(valid.whitelist_type, "custom")

        with self.assertRaisesRegex(ValueError, "invalid whitelist"):
            main.LocalPortRuleCreate(
                port=19262,
                protocol="tcp",
                whitelist_type="custom",
                whitelist_ips="192.0.2.1 } tcp dport 22 accept",
            )

        with self.assertRaisesRegex(ValueError, "single line"):
            main.LocalPortRuleCreate(
                port=19262,
                protocol="tcp",
                comment="first line\nsecond line",
            )

    @patch.object(main, "_commit_nftables")
    @patch.object(main, "_read_nftables")
    def test_local_open_create_commits_input_rule(self, read_nftables, commit):
        read_nftables.return_value = (
            BACKEND_DIR.parent / "configs" / "nftables.conf"
        ).read_text()
        rule = main.LocalPortRuleCreate(
            port=19262,
            protocol="tcp",
            whitelist_type="all",
            comment="Portainer",
        )

        result = main.create_local_port_rule(rule, "tester")

        committed = commit.call_args.args[0]
        input_chain = extract_named_block(committed, "chain input")
        prerouting_chain = extract_named_block(committed, "chain prerouting")
        self.assertEqual(result, {"ok": True})
        self.assertIn("tcp dport 19262 accept # local-open:Portainer", input_chain)
        self.assertNotIn("19262", prerouting_chain)

    def test_local_open_rejects_port_used_by_forwarding(self):
        config = (BACKEND_DIR.parent / "configs" / "nftables.conf").read_text()
        config = main._add_nft_rule(
            config,
            main.NfRuleCreate(
                port=19262,
                protocol="tcp",
                dest_ip="10.0.0.10",
                dest_port=80,
            ),
        )
        rule = main.LocalPortRuleCreate(port=19262, protocol="tcp")

        with patch.object(main, "_read_nftables", return_value=config):
            with self.assertRaises(HTTPException) as raised:
                main.create_local_port_rule(rule, "tester")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("forwarding", raised.exception.detail.lower())

    def test_forwarding_rejects_port_used_by_local_open(self):
        config = (BACKEND_DIR.parent / "configs" / "nftables.conf").read_text()
        config = main._add_local_port_rule(
            config,
            main.LocalPortRuleCreate(port=19262, protocol="tcp"),
        )
        rule = main.NfRuleCreate(
            port=19262,
            protocol="tcp",
            dest_ip="10.0.0.10",
            dest_port=80,
        )

        with patch.object(main, "_read_nftables", return_value=config):
            with self.assertRaises(HTTPException) as raised:
                main.create_nft_rule(rule, "tester")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("local", raised.exception.detail.lower())

    @patch.object(main, "_commit_nftables")
    @patch.object(main, "_read_nftables")
    def test_cn_update_populates_filter_and_nat_sets(
        self, read_nftables, commit
    ):
        read_nftables.return_value = (
            BACKEND_DIR.parent / "configs" / "nftables.conf"
        ).read_text()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"1.0.1.0/24\n"

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            self.assertTrue(main._update_cn_ipset())

        committed = commit.call_args.args[0]
        filter_table = extract_named_block(
            committed, "table inet dmz_webui_filter"
        )
        nat_table = extract_named_block(
            committed, "table ip dmz_webui_nat"
        )
        for table in (filter_table, nat_table):
            self.assertIn("1.0.1.0/24", table)
            self.assertIn("10.0.0.0/8", table)


if __name__ == "__main__":
    unittest.main()
