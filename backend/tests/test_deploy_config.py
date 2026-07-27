import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = PROJECT_ROOT / "scripts" / "common.sh"


class DeployConfigTests(unittest.TestCase):
    def run_validation(self, value: str) -> bool:
        script = (
            f"source {COMMON_SH!s}\n"
            f"validate_icp_number {value!r}\n"
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def test_icp_validation_accepts_empty_and_standard_numbers(self):
        self.assertTrue(self.run_validation(""))
        self.assertTrue(self.run_validation("浙ICP备12345678号"))
        self.assertTrue(self.run_validation("浙ICP备12345678号-1"))

    def test_icp_validation_rejects_invalid_or_unsafe_values(self):
        self.assertFalse(self.run_validation("ICP备2024073394号"))
        self.assertFalse(self.run_validation("浙ICP备ABC号"))
        self.assertFalse(self.run_validation('浙ICP备12345678号"'))
        self.assertFalse(self.run_validation("浙ICP备12345678号\nEnvironment=BAD"))

    def test_config_is_persisted_to_install_and_systemd_templates(self):
        source = COMMON_SH.read_text()
        self.assertIn("DMZ_ICP_NUMBER='${DMZ_ICP_NUMBER:-}'", source)
        self.assertIn('Environment="DMZ_ICP_NUMBER=${DMZ_ICP_NUMBER:-}"', source)


if __name__ == "__main__":
    unittest.main()
