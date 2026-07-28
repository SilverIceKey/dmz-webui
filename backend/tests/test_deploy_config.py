import subprocess
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
