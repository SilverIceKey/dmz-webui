import ipaddress
import os
import re
import subprocess
import json
import time
import threading
import stat
import tempfile
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Query, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator, model_validator
import jwt
import pam

from firewall import (
    apply_owned_rules,
    insert_lines_before_named_block_close,
    normalize_named_block_closing_brace,
    upsert_named_block_in_parent,
)
from caddy_routes import (
    append_caddy_site_route,
    ensure_site_static_directory,
    site_static_directory,
    validate_site_route_conflicts,
)

app = FastAPI(title="DMZ WebUI")

# Metrics history persistence
# 生产环境默认 /var/lib/dmz-webui；开发测试可通过 DMZ_DATA_DIR 覆盖
METRICS_DATA_DIR = os.environ.get("DMZ_DATA_DIR", "/var/lib/dmz-webui")
METRICS_HISTORY_FILE = os.path.join(METRICS_DATA_DIR, "metrics_history.json")
MAX_METRICS_HISTORY = 10
METRICS_COLLECT_INTERVAL = 5
_metrics_history: List[dict] = []
_metrics_lock = threading.Lock()
_metrics_collector_thread: Optional[threading.Thread] = None
_metrics_collector_stop = threading.Event()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.environ.get("DMZ_SECRET_KEY", "dmz-change-me-in-production")
if SECRET_KEY == "dmz-change-me-in-production":
    print("[dmz-webui] WARNING: using default SECRET_KEY, set DMZ_SECRET_KEY env var in production")
ALGORITHM = "HS256"

# Public domain / host used by Caddy reverse proxy generation
DMZ_DOMAIN = os.environ.get("DMZ_DOMAIN", "example.com")
DMZ_WEBUI_HOST = os.environ.get("DMZ_WEBUI_HOST", "127.0.0.1")
DMZ_CADDY_PORT = int(os.environ.get("DMZ_CADDY_PORT", "8443"))
DMZ_CADDY_TLS_MODE = os.environ.get("DMZ_CADDY_TLS_MODE", "manual")
DMZ_ACME_EMAIL = os.environ.get("DMZ_ACME_EMAIL", "").strip()
DMZ_ICP_NUMBER = os.environ.get("DMZ_ICP_NUMBER", "").strip()


def _configured_title(variable_name: str) -> str:
    value = os.environ.get(variable_name, "").strip()
    if (
        not value
        or len(value) > 80
        or any(not character.isprintable() for character in value)
    ):
        return "DMZ WebUI"
    return value


DMZ_SITE_TITLE = _configured_title("DMZ_SITE_TITLE")
DMZ_TAB_TITLE = _configured_title("DMZ_TAB_TITLE")
security = HTTPBearer()

# Paths
NFTABLES_CONF = "/etc/nftables.conf"
CADDYFILE = "/etc/caddy/Caddyfile"
CONFIG_PATH = "/etc/dmz-webui/config.json"
SSL_PROXY_RULES_PATH = "/etc/dmz-webui/ssl_proxy_rules.json"
SITE_ROUTES_PATH = "/etc/dmz-webui/site_routes.json"
SITE_STATIC_ROOT = "/var/lib/dmz-webui/caddy-static"

# ----------------- Models -----------------

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    token: str

class PortRuleBase(BaseModel):
    port: int
    protocol: str = "both"
    comment: Optional[str] = ""
    whitelist_type: str = "all"
    whitelist_ips: Optional[str] = ""

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("tcp", "udp", "both"):
            raise ValueError("protocol must be tcp, udp, or both")
        return v

    @field_validator("whitelist_type")
    @classmethod
    def validate_whitelist_type(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("all", "cn", "abroad", "custom"):
            raise ValueError("whitelist_type must be all, cn, abroad, or custom")
        return v

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, v: Optional[str]) -> Optional[str]:
        if v and ("\n" in v or "\r" in v):
            raise ValueError("comment must be a single line")
        return v

    @model_validator(mode="after")
    def validate_custom_whitelist(self):
        if self.whitelist_type != "custom":
            return self
        values = [
            item.strip()
            for item in (self.whitelist_ips or "").replace(";", ",").split(",")
            if item.strip()
        ]
        if not values:
            raise ValueError(
                "whitelist_ips is required when whitelist_type is custom"
            )
        for value in values:
            try:
                network = ipaddress.ip_network(value, strict=False)
            except ValueError as error:
                raise ValueError(
                    f"invalid whitelist IPv4/CIDR: {value}"
                ) from error
            if network.version != 4:
                raise ValueError(
                    f"whitelist only supports IPv4: {value}"
                )
        return self


class NfRule(PortRuleBase):
    id: int
    dest_ip: str
    dest_port: int


class NfRuleCreate(PortRuleBase):
    dest_ip: str
    dest_port: int


class LocalPortRule(PortRuleBase):
    id: int


class LocalPortRuleCreate(PortRuleBase):
    pass


class SslProxyRule(BaseModel):
    id: int
    port: int
    dest_ip: str
    dest_port: int
    ssl_enabled: bool = True
    comment: Optional[str] = ""

class SslProxyRuleCreate(BaseModel):
    port: int
    dest_ip: str
    dest_port: int
    ssl_enabled: bool = True
    comment: Optional[str] = ""

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if v == DMZ_CADDY_PORT:
            raise ValueError(f"port {DMZ_CADDY_PORT} is reserved for WebUI")
        return v

    @field_validator("dest_ip")
    @classmethod
    def validate_dest_ip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("dest_ip is required")
        return v


class SiteRouteCreate(BaseModel):
    route_type: str
    hostname: str
    path: str
    dest_host: Optional[str] = None
    dest_port: Optional[int] = None
    strip_prefix: bool = True
    ssl_enabled: bool = True
    comment: Optional[str] = ""

    @field_validator("route_type")
    @classmethod
    def validate_route_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("proxy", "static"):
            raise ValueError("route_type must be proxy or static")
        return value

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            value,
        ):
            raise ValueError("invalid hostname")
        domain = DMZ_DOMAIN.lower().rstrip(".")
        if value != domain and not value.endswith(f".{domain}"):
            raise ValueError("hostname must use the configured main domain")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 1:
            value = value.rstrip("/")
        if (
            not re.fullmatch(
                r"/(?:[A-Za-z0-9._~!$&'()+,;=:@%-]+"
                r"(?:/[A-Za-z0-9._~!$&'()+,;=:@%-]+)*)?",
                value,
            )
            or ".." in value
        ):
            raise ValueError("invalid route path")
        return value

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: Optional[str]) -> Optional[str]:
        if value and ("\n" in value or "\r" in value):
            raise ValueError("comment must be a single line")
        return value

    @model_validator(mode="after")
    def validate_route_fields(self):
        domain = DMZ_DOMAIN.lower().rstrip(".")
        if self.hostname == domain:
            reserved = ("/", "/admin", "/assets")
            if self.path == "/" or any(
                self.path == item or self.path.startswith(f"{item}/")
                for item in reserved[1:]
            ):
                raise ValueError("path is reserved by the main domain")
        elif DMZ_CADDY_PORT != 443:
            raise ValueError(
                "subdomain routes require standard port 443 mode"
            )

        if self.route_type == "proxy":
            host = (self.dest_host or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                raise ValueError("invalid proxy destination host")
            if not self.dest_port or not 1 <= self.dest_port <= 65535:
                raise ValueError("proxy destination port must be between 1 and 65535")
            self.dest_host = host
        else:
            self.dest_host = None
            self.dest_port = None
            self.strip_prefix = False
        return self


class SiteRoute(SiteRouteCreate):
    id: int
    static_directory: Optional[str] = None

class ServiceStatus(BaseModel):
    name: str
    active: bool
    status: str

class PortProcess(BaseModel):
    port: int
    protocol: str
    pid: Optional[int] = None
    command: Optional[str] = None
    user: Optional[str] = None

class SystemMetrics(BaseModel):
    cpu_percent: float
    memory: dict
    disk: dict
    network: dict
    load_average: List[float]
    uptime_seconds: int
    boot_time: int

class ApplyRequest(BaseModel):
    service: str

class AppSettings(BaseModel):
    https_enabled: bool = True

class PublicConfig(BaseModel):
    icp_number: str = ""
    site_title: str = "DMZ WebUI"
    tab_title: str = "DMZ WebUI"

# ----------------- Settings -----------------

def load_settings() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"https_enabled": True}

def save_settings(settings: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)

# ----------------- SSL Proxy Rules -----------------

def _load_ssl_proxy_rules() -> List[dict]:
    if os.path.exists(SSL_PROXY_RULES_PATH):
        try:
            with open(SSL_PROXY_RULES_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"[dmz-webui] Failed to load SSL proxy rules: {e}")
    return []

def _save_ssl_proxy_rules(rules: List[dict]):
    _atomic_write_text(SSL_PROXY_RULES_PATH, json.dumps(rules, indent=2))

def _next_ssl_proxy_id(rules: List[dict]) -> int:
    if not rules:
        return 1
    return max(r.get("id", 0) for r in rules) + 1


def _load_site_routes() -> List[dict]:
    if not os.path.exists(SITE_ROUTES_PATH):
        return []
    try:
        with open(SITE_ROUTES_PATH, "r") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except Exception as error:
        print(f"[dmz-webui] Failed to load site routes: {error}")
        return []


def _save_site_routes(rules: List[dict]):
    _atomic_write_text(SITE_ROUTES_PATH, json.dumps(rules, indent=2))


def _next_site_route_id(rules: List[dict]) -> int:
    return max((rule.get("id", 0) for rule in rules), default=0) + 1


def _site_static_directory(rule_id: int) -> str:
    return site_static_directory(SITE_STATIC_ROOT, rule_id)


def _ensure_site_static_directory(rule_id: int) -> str:
    return ensure_site_static_directory(SITE_STATIC_ROOT, rule_id)


def _validate_site_route_conflicts(rules: List[dict]) -> None:
    validate_site_route_conflicts(rules)

# ----------------- Auth -----------------

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/auth/login", response_model=TokenResponse)
def login(req: LoginRequest):
    p = pam.pam()
    if not p.authenticate(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"sub": req.username}, SECRET_KEY, algorithm=ALGORITHM)
    return {"token": token}

# ----------------- Settings API -----------------

@app.get("/api/public-config", response_model=PublicConfig)
def get_public_config():
    return {
        "icp_number": DMZ_ICP_NUMBER,
        "site_title": DMZ_SITE_TITLE,
        "tab_title": DMZ_TAB_TITLE,
    }

@app.get("/api/settings")
def get_settings(_: str = Depends(verify_token)):
    return load_settings()

@app.post("/api/settings")
def update_settings(settings: AppSettings, background_tasks: BackgroundTasks, _: str = Depends(verify_token)):
    save_settings(settings.model_dump())
    _regenerate_caddyfile()
    background_tasks.add_task(_reload_caddy)
    return {"ok": True}

# ----------------- nftables -----------------

def _read_nftables() -> str:
    if os.path.exists(NFTABLES_CONF):
        with open(NFTABLES_CONF, "r") as f:
            return f.read()
    return ""


def _atomic_write_text(path: str, content: str):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory, text=True)
    try:
        if os.path.exists(path):
            os.fchmod(fd, stat.S_IMODE(os.stat(path).st_mode))
        with os.fdopen(fd, "w") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _commit_nftables(content: str):
    """Apply project-owned tables, then atomically persist the validated config."""
    old_content = _read_nftables()
    applied = False
    try:
        apply_owned_rules(content, previous_config_text=old_content)
        applied = True
        _atomic_write_text(NFTABLES_CONF, content)
    except Exception:
        if applied and old_content:
            try:
                apply_owned_rules(old_content, previous_config_text=content)
            except Exception as rollback_error:
                print(f"[dmz-webui] nftables runtime rollback failed: {rollback_error}")
        raise

def _build_whitelist_prefix(whitelist_type: str, whitelist_ips: str) -> str:
    if whitelist_type == "cn":
        return "ip saddr @cn_ipv4 "
    elif whitelist_type == "abroad":
        return "ip saddr != @cn_ipv4 "
    elif whitelist_type == "custom":
        ips = ",".join(ip.strip() for ip in whitelist_ips.replace(";", ",").split(",") if ip.strip())
        if not ips:
            return ""
        return f"ip saddr {{ {ips} }} "
    return ""

def _parse_nft_rules(text: str) -> List[NfRule]:
    raw_rules = []
    # 行尾可选捕获 # 后面的备注内容
    pattern = r"^\s*(?:(ip\s+saddr\s+(?:!=\s+)?(?:@cn_ipv4|\{[^}]*\})\s+))?(tcp|udp)\s+dport\s+(\d+)\s+dnat\s+to\s+([0-9.]+):(\d+)(?:\s*#\s*(.*))?"
    for m in re.finditer(pattern, text, re.MULTILINE):
        whitelist_match = m.group(1)
        protocol = m.group(2)
        port = int(m.group(3))
        dest_ip = m.group(4)
        dest_port = int(m.group(5))
        comment = m.group(6).strip() if m.group(6) else ""

        # Skip rules managed by SSL proxy page
        if comment.startswith("ssl-proxy"):
            continue

        whitelist_type, whitelist_ips = _parse_whitelist(whitelist_match)

        raw_rules.append({
            "protocol": protocol, "port": port, "dest_ip": dest_ip, "dest_port": dest_port,
            "whitelist_type": whitelist_type, "whitelist_ips": whitelist_ips,
            "comment": comment,
        })

    groups = {}
    for r in raw_rules:
        key = (r["port"], r["dest_ip"], r["dest_port"], r["whitelist_type"], r["whitelist_ips"], r["comment"])
        if key not in groups:
            groups[key] = set()
        groups[key].add(r["protocol"])

    rules = []
    for idx, key in enumerate(sorted(groups.keys()), 1):
        port, dest_ip, dest_port, whitelist_type, whitelist_ips, comment = key
        protos = groups[key]
        protocol = "both" if protos == {"tcp", "udp"} else list(protos)[0]
        rules.append(NfRule(
            id=idx, port=port, protocol=protocol, dest_ip=dest_ip, dest_port=dest_port,
            whitelist_type=whitelist_type, whitelist_ips=whitelist_ips, comment=comment,
        ))
    return rules


def _parse_whitelist(
    whitelist_match: Optional[str],
) -> tuple[str, str]:
    if not whitelist_match:
        return "all", ""
    if "!=" in whitelist_match:
        return "abroad", ""
    if "@cn_ipv4" in whitelist_match:
        return "cn", ""
    if "{" in whitelist_match:
        ips_match = re.search(r"\{([^}]*)\}", whitelist_match)
        return "custom", ips_match.group(1).strip() if ips_match else ""
    return "all", ""


def _parse_local_port_rules(text: str) -> List[LocalPortRule]:
    pattern = (
        r"^\s*(?:(ip\s+saddr\s+(?:!=\s+)?(?:@cn_ipv4|\{[^}]*\})\s+))?"
        r"(tcp|udp)\s+dport\s+(\d+)\s+accept\s+"
        r"#\s*local-open(?::(.*))?\s*$"
    )
    grouped: dict[tuple[int, str, str, str], set[str]] = {}
    for match in re.finditer(pattern, text, re.MULTILINE):
        whitelist_type, whitelist_ips = _parse_whitelist(match.group(1))
        key = (
            int(match.group(3)),
            whitelist_type,
            whitelist_ips,
            (match.group(4) or "").strip(),
        )
        grouped.setdefault(key, set()).add(match.group(2))

    rules = []
    for index, key in enumerate(sorted(grouped), 1):
        port, whitelist_type, whitelist_ips, comment = key
        protocols = grouped[key]
        protocol = "both" if protocols == {"tcp", "udp"} else next(iter(protocols))
        rules.append(LocalPortRule(
            id=index,
            port=port,
            protocol=protocol,
            whitelist_type=whitelist_type,
            whitelist_ips=whitelist_ips,
            comment=comment,
        ))
    return rules


def _add_nft_rule(text: str, rule: NfRuleCreate) -> str:
    protocols = ["tcp", "udp"] if rule.protocol == "both" else [rule.protocol]
    prefix = _build_whitelist_prefix(rule.whitelist_type, rule.whitelist_ips or "")
    lines = []
    for proto in protocols:
        line = f"        {prefix}{proto} dport {rule.port} dnat to {rule.dest_ip}:{rule.dest_port}"
        if rule.comment:
            line += f" # {rule.comment}"
        lines.append(line)
    return insert_lines_before_named_block_close(
        text, "chain prerouting", lines
    )


def _add_local_port_rule(text: str, rule: LocalPortRuleCreate) -> str:
    protocols = ["tcp", "udp"] if rule.protocol == "both" else [rule.protocol]
    prefix = _build_whitelist_prefix(
        rule.whitelist_type, rule.whitelist_ips or ""
    )
    marker = "# local-open"
    if rule.comment:
        marker += f":{rule.comment}"
    lines = [
        f"        {prefix}{protocol} dport {rule.port} accept {marker}"
        for protocol in protocols
    ]
    return insert_lines_before_named_block_close(text, "chain input", lines)


def _remove_nft_rule(text: str, port: int, protocol: str, dest_ip: str, dest_port: int) -> str:
    text = normalize_named_block_closing_brace(text, "chain prerouting")
    had_trailing_newline = text.endswith("\n")
    protocols = ["tcp", "udp"] if protocol == "both" else [protocol]
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        skip = False
        for proto in protocols:
            if re.search(rf"^\s*(?:ip\s+saddr\s+(?:!=\s+)?(?:@cn_ipv4|\{{[^}}]*\}})\s+)?\s*{re.escape(proto)}\s+dport\s+{port}\s+dnat\s+to\s+{re.escape(dest_ip)}:{dest_port}", line):
                skip = True
                break
        if not skip:
            new_lines.append(line)
    result = "\n".join(new_lines)
    return result + ("\n" if had_trailing_newline else "")


def _remove_local_port_rule(
    text: str, port: int, protocol: str
) -> str:
    text = normalize_named_block_closing_brace(text, "chain input")
    had_trailing_newline = text.endswith("\n")
    protocols = ["tcp", "udp"] if protocol == "both" else [protocol]
    pattern = re.compile(
        rf"^\s*(?:ip\s+saddr\s+(?:!=\s+)?(?:@cn_ipv4|\{{[^}}]*\}})\s+)?"
        rf"(?:{'|'.join(re.escape(item) for item in protocols)})\s+"
        rf"dport\s+{port}\s+accept\s+#\s*local-open(?::.*)?\s*$"
    )
    kept_lines = [line for line in text.splitlines() if not pattern.search(line)]
    result = "\n".join(kept_lines)
    return result + ("\n" if had_trailing_newline else "")


def _remove_ssl_proxy_nft_rules(text: str) -> str:
    """移除所有由 SSL 代理页面管理的 nftables 规则（input / prerouting 中的标记行）。"""
    text = normalize_named_block_closing_brace(text, "chain input")
    text = normalize_named_block_closing_brace(text, "chain prerouting")
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        if re.search(r"#\s*ssl-proxy:\d+", line):
            continue
        new_lines.append(line)
    result = "\n".join(new_lines)
    return result + ("\n" if had_trailing_newline else "")


def _insert_into_chain(text: str, chain_name: str, new_lines: List[str]) -> str:
    """在指定 chain 的结束 '}' 前插入新行。"""
    return insert_lines_before_named_block_close(
        text, f"chain {chain_name}", new_lines
    )

def _build_ssl_proxy_nftables(rules: List[dict]) -> str:
    text = _read_nftables()
    text = _remove_ssl_proxy_nft_rules(text)

    input_lines = []
    prerouting_lines = []
    for rule in rules:
        port = rule["port"]
        suffix = f"  # ssl-proxy:{port}"
        if rule.get("ssl_enabled"):
            input_lines.append(f"        tcp dport {port} accept{suffix}")
        else:
            prerouting_lines.append(
                f"        tcp dport {port} dnat to {rule['dest_ip']}:{rule['dest_port']}{suffix}"
            )

    text = _insert_into_chain(text, "input", input_lines)
    text = _insert_into_chain(text, "prerouting", prerouting_lines)
    return text


def _apply_ssl_proxy_rules(rules: List[dict]):
    """Atomically apply candidate SSL rules or restore every previous state."""
    old_rules = _load_ssl_proxy_rules()
    old_caddy = _read_caddy()
    old_nftables = _read_nftables()
    new_caddy = _build_caddyfile(rules)
    new_nftables = _build_ssl_proxy_nftables(rules)
    _validate_caddy(new_caddy)

    caddy_changed = False
    nftables_changed = False
    try:
        _write_caddy(new_caddy)
        caddy_changed = True
        _reload_caddy()
        _commit_nftables(new_nftables)
        nftables_changed = True
        _save_ssl_proxy_rules(rules)
    except Exception:
        rollback_errors = []
        if nftables_changed:
            try:
                _commit_nftables(old_nftables)
            except Exception as rollback_error:
                rollback_errors.append(f"nftables: {rollback_error}")
        if caddy_changed:
            try:
                _write_caddy(old_caddy)
                _reload_caddy()
            except Exception as rollback_error:
                rollback_errors.append(f"caddy: {rollback_error}")
        try:
            _save_ssl_proxy_rules(old_rules)
        except Exception as rollback_error:
            rollback_errors.append(f"ssl rules: {rollback_error}")
        if rollback_errors:
            print(f"[dmz-webui] SSL proxy rollback errors: {'; '.join(rollback_errors)}")
        raise

def _check_port_conflict(
    port: int,
    exclude_rule_id: Optional[int] = None,
    exclude_forward: Optional[tuple[str, int, str, int]] = None,
    exclude_local: Optional[tuple[str, int]] = None,
):
    """检查端口是否和 WebUI、现有 SSL 代理规则或防火墙规则冲突。"""
    if port == DMZ_CADDY_PORT:
        raise HTTPException(status_code=400, detail=f"Port {DMZ_CADDY_PORT} is reserved for WebUI")

    ssl_rules = _load_ssl_proxy_rules()
    for r in ssl_rules:
        if r.get("id") == exclude_rule_id:
            continue
        if r["port"] == port:
            raise HTTPException(status_code=400, detail=f"Port {port} is already used by SSL proxy rules")

    nft_text = _read_nftables()
    for line in nft_text.splitlines():
        port_match = re.search(
            rf"\b(tcp|udp)\s+dport\s+{port}\b", line
        )
        if not port_match:
            continue
        protocol = port_match.group(1)
        if re.search(rf"#\s*ssl-proxy:{port}\b", line):
            continue
        if "# local-open" in line:
            if exclude_local:
                old_protocol, old_port = exclude_local
                excluded_protocols = (
                    {"tcp", "udp"} if old_protocol == "both"
                    else {old_protocol}
                )
                if old_port == port and protocol in excluded_protocols:
                    continue
            raise HTTPException(
                status_code=400,
                detail=f"Port {port} is already used by local port rules",
            )
        dnat_match = re.search(
            r"\bdnat\s+to\s+([0-9.]+):(\d+)", line
        )
        if dnat_match:
            if exclude_forward:
                old_protocol, old_port, old_dest_ip, old_dest_port = exclude_forward
                excluded_protocols = (
                    {"tcp", "udp"} if old_protocol == "both"
                    else {old_protocol}
                )
                if (
                    old_port == port
                    and protocol in excluded_protocols
                    and dnat_match.group(1) == old_dest_ip
                    and int(dnat_match.group(2)) == old_dest_port
                ):
                    continue
            raise HTTPException(
                status_code=400,
                detail=f"Port {port} is already used by forwarding rules",
            )
        if re.search(r"\baccept\b", line):
            raise HTTPException(
                status_code=400,
                detail=f"Port {port} is already allowed by system firewall rules",
            )

def _update_cn_ipset() -> bool:
    try:
        import urllib.request
        # Primary source: domestic mirror (fast in CN)
        urls = [
            "https://ispip.clang.cn/all_cn.txt",
            "http://ftp.apnic.net/stats/apnic/delegated-apnic-latest",
        ]

        cidrs = []
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=15) as response:
                    data = response.read().decode('utf-8')
                for line in data.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # ispip.clang.cn format: one CIDR per line
                    if '/' in line:
                        cidrs.append(line)
                    # APNIC format: registry|CN|ipv4|ip|count|date|status
                    elif '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 7 and parts[1] == 'CN' and parts[2] == 'ipv4':
                            ip = parts[3]
                            count = int(parts[4])
                            prefix = 32
                            temp = count
                            while temp > 1:
                                temp >>= 1
                                prefix -= 1
                            cidrs.append(f"{ip}/{prefix}")
                if cidrs:
                    break
            except Exception as e:
                print(f"[dmz-webui] CN ipset source {url} failed: {e}")
                continue

        if not cidrs:
            print("[dmz-webui] All CN ipset sources failed")
            return False

        # Include RFC1918 private networks so LAN traffic is treated as "cn"
        for private in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
            if private not in cidrs:
                cidrs.append(private)

        # Limit to prevent oversized config
        cidrs = cidrs[:5000]

        text = _read_nftables()
        set_block = f"""    set cn_ipv4 {{
        type ipv4_addr
        flags interval
        elements = {{ {', '.join(cidrs)} }}
    }}"""

        text = upsert_named_block_in_parent(
            text,
            "table inet dmz_webui_filter",
            "set cn_ipv4",
            set_block,
            "chain input",
        )
        text = upsert_named_block_in_parent(
            text,
            "table ip dmz_webui_nat",
            "set cn_ipv4",
            set_block,
            "chain prerouting",
        )

        _commit_nftables(text)
        return True
    except Exception as e:
        print(f"[dmz-webui] CN ipset update failed: {e}")
        return False

@app.get("/api/nftables/rules", response_model=List[NfRule])
def get_nft_rules(_: str = Depends(verify_token)):
    text = _read_nftables()
    return _parse_nft_rules(text)

@app.post("/api/nftables/rules")
def create_nft_rule(rule: NfRuleCreate, _: str = Depends(verify_token)):
    _check_port_conflict(rule.port)
    text = _read_nftables()
    text = _add_nft_rule(text, rule)
    _commit_nftables(text)
    return {"ok": True}

@app.put("/api/nftables/rules/{protocol}/{port}")
def edit_nft_rule(protocol: str, port: int, old_dest_ip: str = Query(...), old_dest_port: int = Query(...), rule: NfRuleCreate = ..., _: str = Depends(verify_token)):
    if rule.port != port:
        raise HTTPException(status_code=400, detail="Port cannot be changed")
    _check_port_conflict(
        rule.port,
        exclude_forward=(protocol, port, old_dest_ip, old_dest_port),
    )
    text = _read_nftables()
    text = _remove_nft_rule(text, port, protocol, old_dest_ip, old_dest_port)
    text = _add_nft_rule(text, rule)
    _commit_nftables(text)
    return {"ok": True}

@app.delete("/api/nftables/rules/{protocol}/{port}")
def delete_nft_rule(protocol: str, port: int, dest_ip: str = Query(...), dest_port: int = Query(...), _: str = Depends(verify_token)):
    text = _read_nftables()
    text = _remove_nft_rule(text, port, protocol, dest_ip, dest_port)
    _commit_nftables(text)
    return {"ok": True}


@app.get("/api/nftables/open-ports", response_model=List[LocalPortRule])
def get_local_port_rules(_: str = Depends(verify_token)):
    return _parse_local_port_rules(_read_nftables())


@app.post("/api/nftables/open-ports")
def create_local_port_rule(
    rule: LocalPortRuleCreate, _: str = Depends(verify_token)
):
    _check_port_conflict(rule.port)
    text = _add_local_port_rule(_read_nftables(), rule)
    _commit_nftables(text)
    return {"ok": True}


@app.put("/api/nftables/open-ports/{protocol}/{port}")
def edit_local_port_rule(
    protocol: str,
    port: int,
    rule: LocalPortRuleCreate,
    _: str = Depends(verify_token),
):
    if rule.port != port:
        raise HTTPException(status_code=400, detail="Port cannot be changed")
    _check_port_conflict(
        rule.port,
        exclude_local=(protocol, port),
    )
    text = _read_nftables()
    text = _remove_local_port_rule(text, port, protocol)
    text = _add_local_port_rule(text, rule)
    _commit_nftables(text)
    return {"ok": True}


@app.delete("/api/nftables/open-ports/{protocol}/{port}")
def delete_local_port_rule(
    protocol: str,
    port: int,
    _: str = Depends(verify_token),
):
    text = _remove_local_port_rule(_read_nftables(), port, protocol)
    _commit_nftables(text)
    return {"ok": True}


@app.post("/api/nftables/update-cn-ipset")
def update_cn_ipset(_: str = Depends(verify_token)):
    if _update_cn_ipset():
        return {"ok": True}
    raise HTTPException(status_code=500, detail="Failed to update CN ipset")

# ----------------- SSL Proxy -----------------

@app.get("/api/ssl-proxy/rules", response_model=List[SslProxyRule])
def get_ssl_proxy_rules(_: str = Depends(verify_token)):
    rules = _load_ssl_proxy_rules()
    return [SslProxyRule(**r) for r in rules]

@app.post("/api/ssl-proxy/rules")
def create_ssl_proxy_rule(rule: SslProxyRuleCreate, _: str = Depends(verify_token)):
    _check_port_conflict(rule.port)
    rules = _load_ssl_proxy_rules()
    new_rule = {
        "id": _next_ssl_proxy_id(rules),
        "port": rule.port,
        "dest_ip": rule.dest_ip,
        "dest_port": rule.dest_port,
        "ssl_enabled": rule.ssl_enabled,
        "comment": rule.comment or "",
    }
    rules.append(new_rule)
    try:
        _apply_ssl_proxy_rules(rules)
    except Exception as error:
        raise HTTPException(status_code=500, detail="SSL proxy apply failed; previous configuration restored") from error
    return {"ok": True, "id": new_rule["id"]}

@app.put("/api/ssl-proxy/rules/{rule_id}")
def edit_ssl_proxy_rule(rule_id: int, rule: SslProxyRuleCreate, _: str = Depends(verify_token)):
    rules = _load_ssl_proxy_rules()
    idx = next((i for i, r in enumerate(rules) if r.get("id") == rule_id), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail="Rule not found")
    _check_port_conflict(rule.port, exclude_rule_id=rule_id)
    rules[idx] = {
        "id": rule_id,
        "port": rule.port,
        "dest_ip": rule.dest_ip,
        "dest_port": rule.dest_port,
        "ssl_enabled": rule.ssl_enabled,
        "comment": rule.comment or "",
    }
    try:
        _apply_ssl_proxy_rules(rules)
    except Exception as error:
        raise HTTPException(status_code=500, detail="SSL proxy apply failed; previous configuration restored") from error
    return {"ok": True}

@app.delete("/api/ssl-proxy/rules/{rule_id}")
def delete_ssl_proxy_rule(rule_id: int, _: str = Depends(verify_token)):
    rules = _load_ssl_proxy_rules()
    new_rules = [r for r in rules if r.get("id") != rule_id]
    if len(new_rules) == len(rules):
        raise HTTPException(status_code=404, detail="Rule not found")
    try:
        _apply_ssl_proxy_rules(new_rules)
    except Exception as error:
        raise HTTPException(status_code=500, detail="SSL proxy apply failed; previous configuration restored") from error
    return {"ok": True}


# ----------------- Caddy Site Routes -----------------

def _site_route_response(rule: dict) -> SiteRoute:
    data = dict(rule)
    if data["route_type"] == "static":
        data["static_directory"] = _site_static_directory(data["id"])
    return SiteRoute(**data)


@app.get("/api/caddy/site-routes", response_model=List[SiteRoute])
def get_site_routes(_: str = Depends(verify_token)):
    return [_site_route_response(rule) for rule in _load_site_routes()]


@app.post("/api/caddy/site-routes")
def create_site_route(
    rule: SiteRouteCreate, _: str = Depends(verify_token)
):
    rules = _load_site_routes()
    new_rule = {"id": _next_site_route_id(rules), **rule.model_dump()}
    if new_rule["hostname"] == DMZ_DOMAIN.lower().rstrip("."):
        new_rule["ssl_enabled"] = load_settings().get(
            "https_enabled", True
        )
    candidate = [*rules, new_rule]
    try:
        _validate_site_route_conflicts(candidate)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if new_rule["route_type"] == "static":
        _ensure_site_static_directory(new_rule["id"])
    try:
        _apply_site_routes(candidate)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Site route apply failed; previous configuration restored",
        ) from error
    return {
        "ok": True,
        "id": new_rule["id"],
        "static_directory": (
            _site_static_directory(new_rule["id"])
            if new_rule["route_type"] == "static"
            else None
        ),
    }


@app.put("/api/caddy/site-routes/{rule_id}")
def edit_site_route(
    rule_id: int,
    rule: SiteRouteCreate,
    _: str = Depends(verify_token),
):
    rules = _load_site_routes()
    index = next(
        (item for item, current in enumerate(rules) if current.get("id") == rule_id),
        -1,
    )
    if index == -1:
        raise HTTPException(status_code=404, detail="Site route not found")
    candidate = list(rules)
    candidate[index] = {"id": rule_id, **rule.model_dump()}
    if candidate[index]["hostname"] == DMZ_DOMAIN.lower().rstrip("."):
        candidate[index]["ssl_enabled"] = load_settings().get(
            "https_enabled", True
        )
    try:
        _validate_site_route_conflicts(candidate)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if rule.route_type == "static":
        _ensure_site_static_directory(rule_id)
    try:
        _apply_site_routes(candidate)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Site route apply failed; previous configuration restored",
        ) from error
    return {
        "ok": True,
        "static_directory": (
            _site_static_directory(rule_id)
            if rule.route_type == "static"
            else None
        ),
    }


@app.delete("/api/caddy/site-routes/{rule_id}")
def delete_site_route(rule_id: int, _: str = Depends(verify_token)):
    rules = _load_site_routes()
    candidate = [rule for rule in rules if rule.get("id") != rule_id]
    if len(candidate) == len(rules):
        raise HTTPException(status_code=404, detail="Site route not found")
    try:
        _apply_site_routes(candidate)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Site route apply failed; previous configuration restored",
        ) from error
    return {"ok": True}


# ----------------- Caddy -----------------

def _read_caddy() -> str:
    if os.path.exists(CADDYFILE):
        with open(CADDYFILE, "r") as f:
            return f.read()
    return ""

def _write_caddy(content: str):
    _atomic_write_text(CADDYFILE, content)

def _tls_line(domain: str) -> str:
    cert_dir = f"/etc/letsencrypt/live/{domain}"
    if os.path.isfile(f"{cert_dir}/fullchain.pem") and os.path.isfile(f"{cert_dir}/privkey.pem"):
        return f"tls {cert_dir}/fullchain.pem {cert_dir}/privkey.pem"
    return "tls internal"

def _append_caddy_site_route(lines: List[str], rule: dict) -> None:
    append_caddy_site_route(lines, rule, SITE_STATIC_ROOT)


def _build_caddyfile(
    rules: Optional[List[dict]] = None,
    site_routes: Optional[List[dict]] = None,
) -> str:
    settings = load_settings()
    domain = DMZ_DOMAIN
    configured_site_routes = (
        site_routes if site_routes is not None else _load_site_routes()
    )
    routes_by_hostname: dict[str, List[dict]] = {}
    for rule in configured_site_routes:
        routes_by_hostname.setdefault(rule["hostname"], []).append(rule)
    for hostname_rules in routes_by_hostname.values():
        hostname_rules.sort(
            key=lambda item: len(item["path"]),
            reverse=True,
        )

    if settings.get("https_enabled", True):
        if DMZ_CADDY_TLS_MODE == "auto":
            tls_line = ""
        else:
            tls_line = _tls_line(domain)
    else:
        tls_line = "auto_https off"

    lines = []
    if (
        DMZ_CADDY_TLS_MODE == "auto"
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", DMZ_ACME_EMAIL)
    ):
        lines.extend(["{", f"    email {DMZ_ACME_EMAIL}", "}", ""])
    lines.append(f"{domain}:{DMZ_CADDY_PORT} {{")
    lines.append("    encode gzip")
    if tls_line:
        lines.append(f"    {tls_line}")
    lines.append("")

    for route in routes_by_hostname.pop(domain, []):
        _append_caddy_site_route(lines, route)

    lines.append("    route /admin* {")
    lines.append("        uri strip_prefix /admin")
    lines.append(f"        reverse_proxy {DMZ_WEBUI_HOST}:5000")
    lines.append("    }")
    lines.append("")
    lines.append("    route /assets* {")
    lines.append(f"        reverse_proxy {DMZ_WEBUI_HOST}:5000")
    lines.append("    }")
    lines.append("")

    lines.append("    redir / /admin 302")
    lines.append("}")
    lines.append("")

    for hostname, hostname_routes in sorted(routes_by_hostname.items()):
        ssl_enabled = hostname_routes[0].get("ssl_enabled", True)
        site_address = hostname if ssl_enabled else f"http://{hostname}"
        lines.append(f"{site_address} {{")
        lines.append("    encode gzip")
        lines.append("")
        for route in hostname_routes:
            _append_caddy_site_route(lines, route)
        lines.append("}")
        lines.append("")

    # SSL proxy sites
    for rule in rules if rules is not None else _load_ssl_proxy_rules():
        if not rule.get("ssl_enabled"):
            continue
        port = rule["port"]
        dest = f"{rule['dest_ip']}:{rule['dest_port']}"
        comment = rule.get("comment", "")
        lines.append(f"# ssl-proxy:{port}{(' ' + comment) if comment else ''}")
        lines.append(f"{domain}:{port} {{")
        lines.append("    encode gzip")
        lines.append(f"    {_tls_line(domain)}")
        lines.append(f"    reverse_proxy {dest}")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _apply_site_routes(rules: List[dict]):
    old_caddy = _read_caddy()
    new_caddy = _build_caddyfile(site_routes=rules)
    _validate_caddy(new_caddy)

    caddy_changed = False
    try:
        _write_caddy(new_caddy)
        caddy_changed = True
        _reload_caddy()
        _save_site_routes(rules)
    except Exception:
        if caddy_changed:
            try:
                _write_caddy(old_caddy)
                _reload_caddy()
            except Exception as rollback_error:
                print(
                    "[dmz-webui] site route Caddy rollback failed: "
                    f"{rollback_error}"
                )
        raise


def _regenerate_caddyfile():
    _write_caddy(_build_caddyfile())


def _validate_caddy(content: str):
    directory = os.path.dirname(CADDYFILE)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".Caddyfile.", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        try:
            subprocess.run(
                ["caddy", "validate", "--config", temp_path, "--adapter", "caddyfile"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise RuntimeError(f"Caddy config validation failed: {detail}") from error
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass

def _reload_caddy():
    subprocess.run(["systemctl", "reload", "caddy"], check=True)

# ----------------- Services -----------------

@app.get("/api/services/status")
def get_services(_: str = Depends(verify_token)):
    result = []
    for svc in ["nftables", "caddy"]:
        try:
            out = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
            active = out.stdout.strip() == "active"
            result.append(ServiceStatus(name=svc, active=active, status=out.stdout.strip()))
        except Exception:
            result.append(ServiceStatus(name=svc, active=False, status="unknown"))
    return result

@app.post("/api/services/apply")
def apply_service(req: ApplyRequest, _: str = Depends(verify_token)):
    services_list = []
    if req.service == "all":
        services_list = ["nftables", "caddy"]
    else:
        services_list = [req.service]
    for svc in services_list:
        if svc == "nftables":
            apply_owned_rules(_read_nftables())
        elif svc == "caddy":
            _reload_caddy()
        else:
            subprocess.run(["systemctl", "restart", svc], check=True)
    return {"ok": True, "restarted": services_list}

# ----------------- Port Processes -----------------

@app.get("/api/ports/processes", response_model=List[PortProcess])
def get_port_processes(_: str = Depends(verify_token)):
    result = []
    try:
        out = subprocess.run(["/usr/bin/ss", "-tunlp", "--no-header"], capture_output=True, text=True, check=True, timeout=10)
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            protocol = parts[0]
            local_addr_port = parts[4]
            if ":" not in local_addr_port:
                continue
            addr, port_str = local_addr_port.rsplit(":", 1)
            if not port_str.isdigit():
                continue
            port = int(port_str)

            pid = None
            command = None
            for part in parts[5:]:
                m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', part)
                if m:
                    command = m.group(1)
                    pid = int(m.group(2))
                    break

            result.append(PortProcess(
                port=port,
                protocol=protocol,
                pid=pid,
                command=command,
            ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result

# ----------------- System Metrics -----------------

def _collect_metrics_sync() -> dict:
    """同步采集系统指标（供后台线程和实时接口复用）。"""
    import psutil

    # CPU: initialize reading then sample
    psutil.cpu_percent(interval=None)
    time.sleep(0.3)
    cpu_percent = psutil.cpu_percent(interval=None)

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Network rate: sample twice
    net1 = psutil.net_io_counters()
    time.sleep(0.5)
    net2 = psutil.net_io_counters()
    duration = 0.5
    sent_rate = max(0, (net2.bytes_sent - net1.bytes_sent) / duration)
    recv_rate = max(0, (net2.bytes_recv - net1.bytes_recv) / duration)

    load_avg = list(os.getloadavg())
    boot_time = int(psutil.boot_time())
    uptime_seconds = int(time.time()) - boot_time

    def to_gb(n):
        return round(n / (1024 ** 3), 2)

    return {
        "cpu_percent": round(cpu_percent, 1),
        "memory": {
            "total_gb": to_gb(mem.total),
            "used_gb": to_gb(mem.used),
            "percent": round(mem.percent, 1),
        },
        "disk": {
            "total_gb": to_gb(disk.total),
            "used_gb": to_gb(disk.used),
            "percent": round(disk.percent, 1),
            "path": "/",
        },
        "network": {
            "bytes_sent": net2.bytes_sent,
            "bytes_recv": net2.bytes_recv,
            "sent_rate": round(sent_rate, 1),
            "recv_rate": round(recv_rate, 1),
        },
        "load_average": load_avg,
        "uptime_seconds": uptime_seconds,
        "boot_time": boot_time,
        "server_time": int(time.time()),
    }


def _load_metrics_history() -> List[dict]:
    if not os.path.exists(METRICS_HISTORY_FILE):
        return []
    try:
        with open(METRICS_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data[-MAX_METRICS_HISTORY:]
    except Exception as e:
        print(f"[dmz-webui] Failed to load metrics history: {e}")
    return []


def _save_metrics_history(history: List[dict]):
    try:
        os.makedirs(os.path.dirname(METRICS_HISTORY_FILE), exist_ok=True)
        with open(METRICS_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[dmz-webui] Failed to save metrics history: {e}")


def _record_metric(metric: dict):
    with _metrics_lock:
        _metrics_history.append(metric)
        # 最多保留最近 N 条
        if len(_metrics_history) > MAX_METRICS_HISTORY:
            _metrics_history[:] = _metrics_history[-MAX_METRICS_HISTORY:]
        _save_metrics_history(_metrics_history)


def _metrics_collector_loop():
    """后台线程：定时采集并持久化系统指标。"""
    while not _metrics_collector_stop.is_set():
        try:
            metric = _collect_metrics_sync()
            _record_metric(metric)
        except Exception as e:
            print(f"[dmz-webui] Metrics collector error: {e}")
        _metrics_collector_stop.wait(METRICS_COLLECT_INTERVAL)


@app.on_event("startup")
def _start_metrics_collector():
    global _metrics_collector_thread
    # 加载已有历史数据
    global _metrics_history
    _metrics_history = _load_metrics_history()
    # 启动后台采集线程
    _metrics_collector_stop.clear()
    _metrics_collector_thread = threading.Thread(
        target=_metrics_collector_loop,
        name="dmz-metrics-collector",
        daemon=True,
    )
    _metrics_collector_thread.start()


@app.on_event("shutdown")
def _stop_metrics_collector():
    _metrics_collector_stop.set()
    if _metrics_collector_thread:
        _metrics_collector_thread.join(timeout=2)


@app.get("/api/system/metrics", response_model=SystemMetrics)
def get_system_metrics(_: str = Depends(verify_token)):
    try:
        data = _collect_metrics_sync()
        # 同步记录到历史（避免后台线程未启动或时间窗口差异导致漏采）
        _record_metric(data)
        return SystemMetrics(**data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/metrics/history")
def get_system_metrics_history(_: str = Depends(verify_token)):
    with _metrics_lock:
        # 返回副本，避免外部修改
        return json.loads(json.dumps(_metrics_history))

# ----------------- Self status -----------------

@app.get("/api/status")
def api_status():
    return {"status": "ok", "version": "1.0.0"}

# Static files (must be last)
static_dir = os.path.join(os.path.dirname(__file__), "static")
assets_dir = os.path.join(static_dir, "assets")
if os.path.isdir(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    file_path = os.path.join(static_dir, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(static_dir, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
