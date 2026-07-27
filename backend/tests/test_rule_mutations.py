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


if __name__ == "__main__":
    unittest.main()
