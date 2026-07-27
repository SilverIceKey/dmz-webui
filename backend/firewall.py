"""Apply only the nftables objects owned by DMZ WebUI."""

from __future__ import annotations

import re
import subprocess
from typing import Iterable


OWNED_TABLES = (
    ("inet", "dmz_webui_filter"),
    ("ip", "dmz_webui_nat"),
)

_TABLE_DECLARATION = re.compile(
    r"(?m)^[ \t]*table[ \t]+([a-zA-Z0-9_-]+)[ \t]+([a-zA-Z0-9_.-]+)[ \t]*\{"
)


class FirewallConfigError(ValueError):
    """Raised when a config attempts to escape the DMZ WebUI ownership boundary."""


def _matching_brace(text: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    in_comment = False

    for index in range(opening, len(text)):
        char = text[index]

        if in_comment:
            if char == "\n":
                in_comment = False
            continue

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char == "#":
            in_comment = True
        elif char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index

    raise FirewallConfigError("Unclosed nftables table block")


def extract_owned_tables(config_text: str) -> str:
    """Return a config containing exactly the two tables owned by this project."""
    found: dict[tuple[str, str], str] = {}
    spans: list[tuple[int, int]] = []

    for match in _TABLE_DECLARATION.finditer(config_text):
        family, name = match.group(1), match.group(2)
        key = (family, name)
        if key not in OWNED_TABLES:
            raise FirewallConfigError(
                f"Refusing to apply non-DMZ table: {family} {name}"
            )
        if key in found:
            raise FirewallConfigError(f"Duplicate DMZ table: {family} {name}")

        opening = config_text.find("{", match.start(), match.end())
        closing = _matching_brace(config_text, opening)
        found[key] = config_text[match.start():closing + 1].strip()
        spans.append((match.start(), closing + 1))

    missing = [f"{family} {name}" for family, name in OWNED_TABLES if (family, name) not in found]
    if missing:
        raise FirewallConfigError(
            f"Missing DMZ WebUI table(s): {', '.join(missing)}"
        )

    remainder_parts = []
    cursor = 0
    for start, end in sorted(spans):
        remainder_parts.append(config_text[cursor:start])
        cursor = end
    remainder_parts.append(config_text[cursor:])
    remainder = "".join(remainder_parts)
    unsupported = [
        line.strip()
        for line in remainder.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if unsupported:
        raise FirewallConfigError(
            f"Unsupported top-level nftables statement: {unsupported[0]}"
        )

    return "\n\n".join(found[key] for key in OWNED_TABLES) + "\n"


def _named_block_span(text: str, block_name: str) -> tuple[int, int] | None:
    match = re.search(rf"(?m)^[ \t]*{re.escape(block_name)}\s*\{{", text)
    if not match:
        return None
    opening = text.find("{", match.start(), match.end())
    closing = _matching_brace(text, opening)
    return match.start(), closing + 1


def extract_named_block(text: str, block_name: str) -> str | None:
    """Extract one named nftables block without crossing nested braces."""
    span = _named_block_span(text, block_name)
    if span is None:
        return None
    start, end = span
    return text[start:end]


def replace_named_block(text: str, block_name: str, replacement: str) -> str:
    """Replace one named nftables block without crossing nested braces."""
    span = _named_block_span(text, block_name)
    if span is None:
        return text
    start, end = span
    return text[:start] + replacement + text[end:]


def _run_nft(
    arguments: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["nft", *arguments],
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def _nft_object_exists(arguments: Iterable[str]) -> bool:
    result = _run_nft(["list", *arguments])
    return result.returncode == 0


def build_owned_replace_batch(config_text: str) -> str:
    """Build an atomic batch that replaces only project-owned tables."""
    owned_config = extract_owned_tables(config_text)
    commands = []
    for family, name in OWNED_TABLES:
        if _nft_object_exists(["table", family, name]):
            commands.append(f"delete table {family} {name}")
    commands.append(owned_config.rstrip())
    return "\n".join(commands) + "\n"


def build_legacy_cleanup_batch() -> str:
    """Build a guarded one-time cleanup for the project's pre-ownership layout."""
    commands: list[str] = []
    legacy_groups = (
        (
            ("set", "inet", "filter", "ssh_ports"),
            (
                ("chain", "inet", "filter", "input"),
                ("chain", "inet", "filter", "forward"),
                ("chain", "inet", "filter", "output"),
            ),
        ),
        (
            ("set", "ip", "nat", "cn_ipv4"),
            (
                ("chain", "ip", "nat", "prerouting"),
                ("chain", "ip", "nat", "postrouting"),
            ),
        ),
    )

    for marker, chains in legacy_groups:
        if not _nft_object_exists(marker):
            continue
        for chain in chains:
            if _nft_object_exists(chain):
                _, family, table, name = chain
                commands.append(f"flush chain {family} {table} {name}")
                commands.append(f"delete chain {family} {table} {name}")
        _, family, table, name = marker
        commands.append(f"delete set {family} {table} {name}")

    return "\n".join(commands) + ("\n" if commands else "")


def _execute_checked_batch(batch: str) -> None:
    try:
        _run_nft(["-c", "-f", "-"], input_text=batch, check=True)
        _run_nft(["-f", "-"], input_text=batch, check=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(f"nftables apply failed: {detail}") from error


def apply_owned_rules(config_text: str, *, migrate_legacy: bool = False) -> None:
    """Atomically replace DMZ WebUI tables and optionally clean its legacy objects."""
    _execute_checked_batch(build_owned_replace_batch(config_text))

    if migrate_legacy:
        cleanup_batch = build_legacy_cleanup_batch()
        if cleanup_batch:
            _execute_checked_batch(cleanup_batch)
