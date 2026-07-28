import sys
import types
import unittest
from pathlib import Path
from unittest.mock import call, patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

if "pam" not in sys.modules:
    fake_pam = types.ModuleType("pam")
    fake_pam.pam = object
    sys.modules["pam"] = fake_pam

import main
from fastapi import HTTPException


SNI_ROUTE = {
    "id": 1,
    "hostname": "derper.example.com",
    "dest_host": "127.0.0.1",
    "dest_port": 41103,
    "comment": "DERP",
}

SITE_ROUTE = {
    "id": 2,
    "route_type": "proxy",
    "hostname": "headscale.example.com",
    "path": "/",
    "dest_host": "127.0.0.1",
    "dest_port": 9091,
    "strip_prefix": False,
    "ssl_enabled": True,
    "comment": "Headscale",
}


class SniRouteValidationTests(unittest.TestCase):
    def test_accepts_subdomain_in_standard_443_mode(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "www.example.com"),
            patch.object(main, "DMZ_ROUTE_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
        ):
            route = main.SniRouteCreate(
                hostname="DERPER.example.com.",
                dest_host="127.0.0.1",
                dest_port=41103,
            )

        self.assertEqual(route.hostname, "derper.example.com")

    def test_rejects_nonstandard_mode_and_main_webui_hostname(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "www.example.com"),
            patch.object(main, "DMZ_ROUTE_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 8443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "manual"),
        ):
            with self.assertRaisesRegex(ValueError, "standard port 443"):
                main.SniRouteCreate(
                    hostname="derper.example.com",
                    dest_host="127.0.0.1",
                    dest_port=41103,
                )

        with (
            patch.object(main, "DMZ_DOMAIN", "www.example.com"),
            patch.object(main, "DMZ_ROUTE_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
        ):
            with self.assertRaisesRegex(ValueError, "reserved"):
                main.SniRouteCreate(
                    hostname="www.example.com",
                    dest_host="127.0.0.1",
                    dest_port=41103,
                )

    def test_rejects_duplicate_and_http_site_hostname(self):
        with self.assertRaisesRegex(ValueError, "already configured"):
            main._validate_sni_route_conflicts(
                [SNI_ROUTE, {**SNI_ROUTE, "id": 2}],
                [],
            )

        with self.assertRaisesRegex(ValueError, "HTTP site route"):
            main._validate_sni_route_conflicts(
                [{**SNI_ROUTE, "hostname": "headscale.example.com"}],
                [SITE_ROUTE],
            )


class SniCaddyGenerationTests(unittest.TestCase):
    def test_generates_listener_wrapper_before_existing_http_sites(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "www.example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
            patch.object(main, "DMZ_ACME_EMAIL", "ops@example.com"),
            patch.object(main, "_load_site_routes", return_value=[SITE_ROUTE]),
            patch.object(main, "_load_sni_routes", return_value=[SNI_ROUTE]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(
                main,
                "load_settings",
                return_value={"https_enabled": True},
            ),
        ):
            generated = main._build_caddyfile()

        self.assertIn("servers :443 {", generated)
        self.assertIn("listener_wrappers {", generated)
        self.assertIn(
            "@sni_route_1 tls sni derper.example.com",
            generated,
        )
        self.assertIn("proxy tcp/127.0.0.1:41103", generated)
        self.assertIn("\n            tls\n", generated)
        self.assertIn("headscale.example.com {", generated)
        self.assertIn("www.example.com:443 {", generated)

    def test_no_sni_routes_preserves_global_options_without_wrapper(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
            patch.object(main, "DMZ_ACME_EMAIL", "ops@example.com"),
            patch.object(main, "_load_site_routes", return_value=[]),
            patch.object(main, "_load_sni_routes", return_value=[]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(
                main,
                "load_settings",
                return_value={"https_enabled": True},
            ),
        ):
            generated = main._build_caddyfile()

        self.assertTrue(generated.startswith("{\n    email ops@example.com\n}"))
        self.assertNotIn("listener_wrappers", generated)

    def test_existing_sni_routes_block_switch_to_nonstandard_mode(self):
        with (
            patch.object(main, "DMZ_CADDY_PORT", 8443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "manual"),
            patch.object(main, "_load_site_routes", return_value=[]),
            patch.object(main, "_load_sni_routes", return_value=[SNI_ROUTE]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(
                main,
                "load_settings",
                return_value={"https_enabled": True},
            ),
        ):
            with self.assertRaisesRegex(ValueError, "standard port 443"):
                main._build_caddyfile()


class SniRouteTransactionTests(unittest.TestCase):
    @patch.object(main, "_save_sni_routes")
    @patch.object(main, "_reload_caddy")
    @patch.object(main, "_write_caddy")
    @patch.object(main, "_validate_caddy")
    @patch.object(main, "_build_caddyfile", return_value="new caddy")
    @patch.object(main, "_check_caddy_layer4_modules")
    @patch.object(main, "_validate_sni_route_conflicts")
    @patch.object(main, "_read_caddy", return_value="old caddy")
    @patch.object(main, "_load_sni_routes", return_value=[])
    def test_success_saves_json_after_reload(
        self,
        _load,
        _read,
        _conflicts,
        check_modules,
        _build,
        validate,
        write,
        reload_caddy,
        save,
    ):
        main._apply_sni_routes([SNI_ROUTE])

        check_modules.assert_called_once_with()
        validate.assert_called_once_with("new caddy")
        write.assert_called_once_with("new caddy")
        reload_caddy.assert_called_once_with()
        save.assert_called_once_with([SNI_ROUTE])

    @patch.object(main, "_save_sni_routes")
    @patch.object(main, "_reload_caddy", side_effect=[
        RuntimeError("reload failed"),
        None,
    ])
    @patch.object(main, "_write_caddy")
    @patch.object(main, "_validate_caddy")
    @patch.object(main, "_build_caddyfile", return_value="new caddy")
    @patch.object(main, "_check_caddy_layer4_modules")
    @patch.object(main, "_validate_sni_route_conflicts")
    @patch.object(main, "_read_caddy", return_value="old caddy")
    @patch.object(main, "_load_sni_routes", return_value=[SNI_ROUTE])
    def test_reload_failure_restores_caddy_and_json(
        self,
        _load,
        _read,
        _conflicts,
        _modules,
        _build,
        _validate,
        write,
        _reload,
        save,
    ):
        candidate = [{**SNI_ROUTE, "dest_port": 41104}]

        with self.assertRaisesRegex(RuntimeError, "reload failed"):
            main._apply_sni_routes(candidate)

        self.assertEqual(
            write.call_args_list,
            [call("new caddy"), call("old caddy")],
        )
        self.assertEqual(
            save.call_args_list,
            [call([SNI_ROUTE])],
        )

    @patch.object(main, "_save_sni_routes", side_effect=[
        OSError("disk full"),
        None,
    ])
    @patch.object(main, "_reload_caddy")
    @patch.object(main, "_write_caddy")
    @patch.object(main, "_validate_caddy")
    @patch.object(main, "_build_caddyfile", return_value="new caddy")
    @patch.object(main, "_check_caddy_layer4_modules")
    @patch.object(main, "_validate_sni_route_conflicts")
    @patch.object(main, "_read_caddy", return_value="old caddy")
    @patch.object(main, "_load_sni_routes", return_value=[SNI_ROUTE])
    def test_json_failure_restores_caddy_and_previous_json(
        self,
        _load,
        _read,
        _conflicts,
        _modules,
        _build,
        _validate,
        write,
        reload_caddy,
        save,
    ):
        candidate = [{**SNI_ROUTE, "dest_port": 41104}]

        with self.assertRaisesRegex(OSError, "disk full"):
            main._apply_sni_routes(candidate)

        self.assertEqual(
            write.call_args_list,
            [call("new caddy"), call("old caddy")],
        )
        self.assertEqual(reload_caddy.call_count, 2)
        self.assertEqual(
            save.call_args_list,
            [call(candidate), call([SNI_ROUTE])],
        )

    @patch.object(main, "_save_sni_routes")
    @patch.object(main, "_reload_caddy")
    @patch.object(main, "_write_caddy")
    @patch.object(main, "_validate_caddy")
    @patch.object(main, "_build_caddyfile", return_value="plain caddy")
    @patch.object(main, "_check_caddy_layer4_modules")
    @patch.object(main, "_validate_sni_route_conflicts")
    @patch.object(main, "_read_caddy", return_value="old caddy")
    @patch.object(main, "_load_sni_routes", return_value=[SNI_ROUTE])
    def test_removing_last_route_does_not_require_layer4_module(
        self,
        _load,
        _read,
        _conflicts,
        check_modules,
        _build,
        _validate,
        _write,
        _reload,
        _save,
    ):
        main._apply_sni_routes([])

        check_modules.assert_not_called()

    @patch.object(main.subprocess, "run")
    def test_module_check_reports_missing_capability(self, run):
        run.return_value.stdout = "http.handlers.reverse_proxy\n"

        with self.assertRaisesRegex(
            main.CaddyCapabilityError,
            "caddy.listeners.layer4",
        ):
            main._check_caddy_layer4_modules()


class SniRouteEndpointTests(unittest.TestCase):
    def test_create_reports_missing_layer4_modules(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "www.example.com"),
            patch.object(main, "DMZ_ROUTE_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
        ):
            rule = main.SniRouteCreate(
                hostname="derper.example.com",
                dest_host="127.0.0.1",
                dest_port=41103,
            )

        with (
            patch.object(main, "_load_sni_routes", return_value=[]),
            patch.object(main, "_validate_sni_route_conflicts"),
            patch.object(
                main,
                "_apply_sni_routes",
                side_effect=main.CaddyCapabilityError(
                    "Caddy Layer 4 modules are not installed"
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                main.create_sni_route(rule, "tester")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("not installed", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
