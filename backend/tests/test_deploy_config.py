import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = PROJECT_ROOT / "scripts" / "common.sh"


class DeployConfigTests(unittest.TestCase):
    def run_validation(self, function_name: str, value: str) -> bool:
        script = (
            f"source {COMMON_SH!s}\n"
            f"{function_name} {value!r}\n"
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def test_icp_validation_accepts_empty_and_standard_numbers(self):
        self.assertTrue(self.run_validation("validate_icp_number", ""))
        self.assertTrue(self.run_validation(
            "validate_icp_number", "浙ICP备12345678号"
        ))
        self.assertTrue(self.run_validation(
            "validate_icp_number", "浙ICP备12345678号-1"
        ))

    def test_icp_validation_rejects_invalid_or_unsafe_values(self):
        self.assertFalse(self.run_validation(
            "validate_icp_number", "ICP备2024073394号"
        ))
        self.assertFalse(self.run_validation(
            "validate_icp_number", "浙ICP备ABC号"
        ))
        self.assertFalse(self.run_validation(
            "validate_icp_number", '浙ICP备12345678号"'
        ))
        self.assertFalse(self.run_validation(
            "validate_icp_number",
            "浙ICP备12345678号\nEnvironment=BAD",
        ))

    def test_title_validation_accepts_unicode_and_rejects_unsafe_values(self):
        self.assertTrue(self.run_validation("validate_title", "银钥网络管理"))
        self.assertFalse(self.run_validation("validate_title", ""))
        self.assertFalse(self.run_validation(
            "validate_title", "a" * 81
        ))
        self.assertFalse(self.run_validation(
            "validate_title", 'title" Environment=BAD'
        ))
        self.assertFalse(self.run_validation(
            "validate_title", "title\nEnvironment=BAD"
        ))

    def test_title_prompt_supports_update_and_default_reset(self):
        script = (
            f"source {COMMON_SH!s}\n"
            "DMZ_SITE_TITLE='旧标题'\n"
            "prompt_title_config DMZ_SITE_TITLE '站点标题' <<< '  新标题  '\n"
            'test "$DMZ_SITE_TITLE" = "新标题"\n'
            "prompt_title_config DMZ_SITE_TITLE '站点标题' <<< '-'\n"
            'test "$DMZ_SITE_TITLE" = "DMZ WebUI"\n'
        )
        result = subprocess.run(
            ["bash", "-uo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_config_is_persisted_to_install_and_systemd_templates(self):
        source = COMMON_SH.read_text()
        self.assertIn("DMZ_ICP_NUMBER='${DMZ_ICP_NUMBER:-}'", source)
        self.assertIn('Environment="DMZ_ICP_NUMBER=${DMZ_ICP_NUMBER:-}"', source)
        self.assertIn(
            "DMZ_SITE_TITLE='${DMZ_SITE_TITLE:-DMZ WebUI}'",
            source,
        )
        self.assertIn(
            "DMZ_TAB_TITLE='${DMZ_TAB_TITLE:-DMZ WebUI}'",
            source,
        )
        self.assertIn(
            'Environment="DMZ_SITE_TITLE=${DMZ_SITE_TITLE:-DMZ WebUI}"',
            source,
        )
        self.assertIn(
            'Environment="DMZ_TAB_TITLE=${DMZ_TAB_TITLE:-DMZ WebUI}"',
            source,
        )
        self.assertIn("DMZ_ROUTE_DOMAIN=", source)
        self.assertIn('Environment="DMZ_ROUTE_DOMAIN=', source)

    def test_existing_config_confirms_groups_and_only_changes_branding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "install.conf"
            config_file.write_text(
                "\n".join([
                    "DMZ_DOMAIN='www.example.com'",
                    "DMZ_WEBUI_HOST='127.0.0.1'",
                    "CADDY_MODE='standard'",
                    "DMZ_CADDY_PORT='443'",
                    "DMZ_CADDY_TLS_MODE='auto'",
                    "DMZ_ICP_NUMBER='浙ICP备12345678号'",
                    "DMZ_SITE_TITLE='旧站点'",
                    "DMZ_TAB_TITLE='旧页签'",
                    "ACME_EMAIL='ops@example.com'",
                    "",
                ])
            )
            script = (
                "info() { :; }\n"
                "warn() { :; }\n"
                f"source {COMMON_SH!s}\n"
                f"CONFIG_FILE={str(config_file)!r}\n"
                "prompt_config <<'INPUT'\n"
                "n\n"
                "y\n"
                "新站点\n"
                "新页签\n"
                "n\n"
                "INPUT\n"
                "source \"$CONFIG_FILE\"\n"
                'test "$DMZ_DOMAIN" = "www.example.com"\n'
                'test "$DMZ_ROUTE_DOMAIN" = "example.com"\n'
                'test "$CADDY_MODE" = "standard"\n'
                'test "$DMZ_CADDY_PORT" = "443"\n'
                'test "$DMZ_CADDY_TLS_MODE" = "auto"\n'
                'test "$DMZ_SITE_TITLE" = "新站点"\n'
                'test "$DMZ_TAB_TITLE" = "新页签"\n'
                'test "$DMZ_ICP_NUMBER" = "浙ICP备12345678号"\n'
            )
            result = subprocess.run(
                ["bash", "-uo", "pipefail", "-c", script],
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_caddy_group_keeps_current_mode_on_empty_input(self):
        script = (
            "info() { :; }\n"
            "warn() { :; }\n"
            f"source {COMMON_SH!s}\n"
            "DMZ_DOMAIN='example.com'\n"
            "DMZ_WEBUI_HOST='127.0.0.1'\n"
            "CADDY_MODE='standard'\n"
            "DMZ_CADDY_PORT='443'\n"
            "DMZ_CADDY_TLS_MODE='auto'\n"
            "ACME_EMAIL='ops@example.com'\n"
            "prompt_public_caddy_config <<'INPUT'\n"
            "\n"
            "\n"
            "\n"
            "\n"
            "\n"
            "INPUT\n"
            'test "$CADDY_MODE" = "standard"\n'
            'test "$DMZ_CADDY_PORT" = "443"\n'
            'test "$DMZ_CADDY_TLS_MODE" = "auto"\n'
            'test "$ACME_EMAIL" = "ops@example.com"\n'
        )
        result = subprocess.run(
            ["bash", "-uo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_www_domain_defaults_route_domain_to_parent(self):
        script = (
            f"source {COMMON_SH!s}\n"
            'test "$(default_route_domain www.silvericekey.top)" '
            '= "silvericekey.top"\n'
            'test "$(default_route_domain example.com)" = "example.com"\n'
        )
        result = subprocess.run(
            ["bash", "-uo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_config_flow_has_no_global_reuse_shortcut(self):
        source = COMMON_SH.read_text()
        self.assertNotIn("是否复用? [Y/n]", source)
        self.assertIn("是否修改公网与 Caddy 配置？", source)
        self.assertIn("是否修改页面标题配置？", source)
        self.assertIn("是否修改备案配置？", source)

    def test_deploy_and_update_use_complete_python_caddy_generator(self):
        common = COMMON_SH.read_text()
        deploy = (PROJECT_ROOT / "scripts" / "deploy.sh").read_text()
        update = (PROJECT_ROOT / "scripts" / "update.sh").read_text()

        self.assertIn("scripts/generate_caddyfile.py", common)
        self.assertNotIn("CADDYEOF", common)
        self.assertIn('DMZ_ACME_EMAIL="${ACME_EMAIL:-}"', common)
        self.assertIn('Environment="DMZ_ACME_EMAIL=${ACME_EMAIL:-}"', common)
        self.assertIn("generate_caddyfile", deploy)
        self.assertIn("generate_caddyfile", update)


if __name__ == "__main__":
    unittest.main()
