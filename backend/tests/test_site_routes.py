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


PROXY_ROUTE = {
    "id": 1,
    "route_type": "proxy",
    "hostname": "headscale.example.com",
    "path": "/",
    "dest_host": "127.0.0.1",
    "dest_port": 9091,
    "strip_prefix": False,
    "ssl_enabled": True,
    "comment": "Headscale",
}

STATIC_ROUTE = {
    "id": 2,
    "route_type": "static",
    "hostname": "example.com",
    "path": "/derper.json",
    "dest_host": None,
    "dest_port": None,
    "strip_prefix": False,
    "ssl_enabled": True,
    "comment": "DERP map",
}


class SiteRouteValidationTests(unittest.TestCase):
    def test_accepts_main_domain_and_subdomain(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
        ):
            route = main.SiteRouteCreate(
                route_type="proxy",
                hostname="headscale.example.com",
                path="/",
                dest_host="127.0.0.1",
                dest_port=9091,
                ssl_enabled=True,
            )

        self.assertEqual(route.hostname, "headscale.example.com")

    def test_rejects_foreign_domain_and_reserved_main_path(self):
        with patch.object(main, "DMZ_DOMAIN", "example.com"):
            with self.assertRaisesRegex(ValueError, "main domain"):
                main.SiteRouteCreate(
                    route_type="proxy",
                    hostname="foreign.test",
                    path="/",
                    dest_host="127.0.0.1",
                    dest_port=9091,
                )
            with self.assertRaisesRegex(ValueError, "reserved"):
                main.SiteRouteCreate(
                    route_type="static",
                    hostname="example.com",
                    path="/admin",
                )

    def test_rejects_caddy_matcher_injection_in_path(self):
        with patch.object(main, "DMZ_DOMAIN", "example.com"):
            with self.assertRaisesRegex(ValueError, "invalid route path"):
                main.SiteRouteCreate(
                    route_type="static",
                    hostname="example.com",
                    path='/file"}',
                )

    def test_normalizes_trailing_path_separator(self):
        with patch.object(main, "DMZ_DOMAIN", "example.com"):
            route = main.SiteRouteCreate(
                route_type="static",
                hostname="example.com",
                path="/derper.json/",
            )

        self.assertEqual(route.path, "/derper.json")

    def test_rejects_overlapping_paths_on_same_hostname(self):
        candidate = [
            PROXY_ROUTE,
            {
                **STATIC_ROUTE,
                "hostname": "headscale.example.com",
                "path": "/derper.json",
            },
        ]

        with self.assertRaisesRegex(ValueError, "overlaps"):
            main._validate_site_route_conflicts(candidate)


class CaddySiteGenerationTests(unittest.TestCase):
    def test_builds_subdomain_proxy_and_main_domain_static_file(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
            patch.object(main, "_load_site_routes", return_value=[
                PROXY_ROUTE,
                STATIC_ROUTE,
            ]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(main, "load_settings", return_value={
                "https_enabled": True,
            }),
        ):
            generated = main._build_caddyfile()

        self.assertIn("headscale.example.com {", generated)
        self.assertIn("reverse_proxy 127.0.0.1:9091", generated)
        self.assertIn("header_up True-Client-IP {remote_host}", generated)
        self.assertIn("example.com {", generated)
        self.assertIn("route /derper.json", generated)
        self.assertIn(
            "root * /var/lib/dmz-webui/caddy-static/2",
            generated,
        )
        self.assertIn("route /admin*", generated)

    def test_non_root_proxy_can_strip_prefix(self):
        route = {
            **PROXY_ROUTE,
            "hostname": "example.com",
            "path": "/service",
            "strip_prefix": True,
        }
        with (
            patch.object(main, "DMZ_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
            patch.object(main, "_load_site_routes", return_value=[route]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(main, "load_settings", return_value={
                "https_enabled": True,
            }),
        ):
            generated = main._build_caddyfile()

        self.assertIn("path /service /service/*", generated)
        self.assertIn("uri strip_prefix /service", generated)

    def test_ssl_disabled_subdomain_uses_explicit_http_site(self):
        route = {**PROXY_ROUTE, "ssl_enabled": False}
        with (
            patch.object(main, "DMZ_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
            patch.object(main, "_load_site_routes", return_value=[route]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(main, "load_settings", return_value={
                "https_enabled": True,
            }),
        ):
            generated = main._build_caddyfile()

        self.assertIn("http://headscale.example.com {", generated)

    def test_auto_https_includes_configured_acme_email(self):
        with (
            patch.object(main, "DMZ_DOMAIN", "example.com"),
            patch.object(main, "DMZ_CADDY_PORT", 443),
            patch.object(main, "DMZ_CADDY_TLS_MODE", "auto"),
            patch.object(main, "DMZ_ACME_EMAIL", "ops@example.com"),
            patch.object(main, "_load_site_routes", return_value=[PROXY_ROUTE]),
            patch.object(main, "_load_ssl_proxy_rules", return_value=[]),
            patch.object(main, "load_settings", return_value={
                "https_enabled": True,
            }),
        ):
            generated = main._build_caddyfile()

        self.assertTrue(generated.startswith("{\n    email ops@example.com\n}"))


class SiteRouteTransactionTests(unittest.TestCase):
    @patch.object(main, "_save_site_routes")
    @patch.object(main, "_reload_caddy")
    @patch.object(main, "_write_caddy")
    @patch.object(main, "_validate_caddy")
    @patch.object(main, "_build_caddyfile", return_value="new caddy")
    @patch.object(main, "_read_caddy", return_value="old caddy")
    @patch.object(main, "_load_site_routes", return_value=[])
    def test_success_saves_json_after_caddy_reload(
        self,
        _load,
        _read,
        _build,
        validate,
        write,
        reload_caddy,
        save,
    ):
        main._apply_site_routes([PROXY_ROUTE])

        validate.assert_called_once_with("new caddy")
        write.assert_called_once_with("new caddy")
        reload_caddy.assert_called_once_with()
        save.assert_called_once_with([PROXY_ROUTE])

    @patch.object(main, "_save_site_routes")
    @patch.object(main, "_reload_caddy", side_effect=[
        RuntimeError("reload failed"),
        None,
    ])
    @patch.object(main, "_write_caddy")
    @patch.object(main, "_validate_caddy")
    @patch.object(main, "_build_caddyfile", return_value="new caddy")
    @patch.object(main, "_read_caddy", return_value="old caddy")
    @patch.object(main, "_load_site_routes", return_value=[])
    def test_reload_failure_restores_previous_caddy(
        self,
        _load,
        _read,
        _build,
        _validate,
        write,
        _reload,
        save,
    ):
        with self.assertRaisesRegex(RuntimeError, "reload failed"):
            main._apply_site_routes([PROXY_ROUTE])

        self.assertEqual(
            write.call_args_list,
            [call("new caddy"), call("old caddy")],
        )
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
