import os
from typing import List


def site_static_directory(static_root: str, rule_id: int) -> str:
    return os.path.join(static_root, str(rule_id))


def ensure_site_static_directory(static_root: str, rule_id: int) -> str:
    os.makedirs(static_root, mode=0o755, exist_ok=True)
    os.chmod(static_root, 0o755)
    directory = site_static_directory(static_root, rule_id)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    os.chmod(directory, 0o755)
    return directory


def paths_overlap(first: str, second: str) -> bool:
    if first == "/" or second == "/":
        return True
    return (
        first == second
        or first.startswith(f"{second}/")
        or second.startswith(f"{first}/")
    )


def validate_site_route_conflicts(rules: List[dict]) -> None:
    for index, rule in enumerate(rules):
        for other in rules[index + 1:]:
            if rule["hostname"] != other["hostname"]:
                continue
            if rule.get("ssl_enabled", True) != other.get("ssl_enabled", True):
                raise ValueError(
                    f"hostname {rule['hostname']} has conflicting SSL settings"
                )
            if paths_overlap(rule["path"], other["path"]):
                raise ValueError(
                    f"route {rule['hostname']}{rule['path']} overlaps "
                    f"{other['hostname']}{other['path']}"
                )


def validate_sni_route_conflicts(
    sni_routes: List[dict],
    site_routes: List[dict],
) -> None:
    seen_hostnames: set[str] = set()
    site_hostnames = {route["hostname"] for route in site_routes}
    for route in sni_routes:
        hostname = route["hostname"]
        if hostname in seen_hostnames:
            raise ValueError(f"SNI hostname {hostname} is already configured")
        if hostname in site_hostnames:
            raise ValueError(
                f"hostname {hostname} is already used by an HTTP site route"
            )
        seen_hostnames.add(hostname)


def append_caddy_sni_listener(
    lines: List[str],
    rules: List[dict],
) -> None:
    lines.append("    servers :443 {")
    lines.append("        listener_wrappers {")
    lines.append("            layer4 {")
    for rule in rules:
        route_id = rule["id"]
        lines.append(
            f"                @sni_route_{route_id} tls sni {rule['hostname']}"
        )
        lines.append(f"                route @sni_route_{route_id} {{")
        lines.append(
            "                    proxy "
            f"tcp/{rule['dest_host']}:{rule['dest_port']}"
        )
        lines.append("                }")
        lines.append("")
    lines.append("            }")
    lines.append("            tls")
    lines.append("        }")
    lines.append("    }")


def append_caddy_site_route(
    lines: List[str],
    rule: dict,
    static_root: str,
) -> None:
    route_id = rule["id"]
    path = rule["path"]
    matcher = ""
    if path != "/" and rule["route_type"] == "proxy":
        matcher = f"@site_route_{route_id}"
        lines.append(f"    {matcher} path {path} {path}/*")
    elif path != "/":
        matcher = path

    lines.append(f"    route {matcher} {{" if matcher else "    route {")
    if rule["route_type"] == "proxy":
        if path != "/" and rule.get("strip_prefix", True):
            lines.append(f"        uri strip_prefix {path}")
        lines.append(
            f"        reverse_proxy {rule['dest_host']}:{rule['dest_port']} {{"
        )
        lines.append("            header_up True-Client-IP {remote_host}")
        lines.append("            header_up X-Real-IP {remote_host}")
        lines.append("        }")
    else:
        lines.append(
            f"        root * {site_static_directory(static_root, route_id)}"
        )
        lines.append("        file_server")
    lines.append("    }")
    lines.append("")
