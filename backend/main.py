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

from firewall import apply_owned_rules, replace_named_block

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
DMZ_ICP_NUMBER = os.environ.get("DMZ_ICP_NUMBER", "").strip()
security = HTTPBearer()

# Paths
NFTABLES_CONF = "/etc/nftables.conf"
CADDYFILE = "/etc/caddy/Caddyfile"
CONFIG_PATH = "/etc/dmz-webui/config.json"
SSL_PROXY_RULES_PATH = "/etc/dmz-webui/ssl_proxy_rules.json"

# ----------------- Models -----------------

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    token: str

class NfRule(BaseModel):
    id: int
    port: int
    protocol: str
    dest_ip: str
    dest_port: int
    comment: Optional[str] = ""
    whitelist_type: str = "all"
    whitelist_ips: Optional[str] = ""

class NfRuleCreate(BaseModel):
    port: int
    protocol: str = "both"
    dest_ip: str
    dest_port: int
    comment: Optional[str] = ""
    whitelist_type: str = "all"
    whitelist_ips: Optional[str] = ""

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

    @model_validator(mode="after")
    def validate_custom_whitelist(self):
        if self.whitelist_type == "custom" and not (self.whitelist_ips or "").strip():
            raise ValueError("whitelist_ips is required when whitelist_type is custom")
        return self

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
    return {"icp_number": DMZ_ICP_NUMBER}

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

        if whitelist_match:
            if "!=" in whitelist_match:
                whitelist_type = "abroad"
                whitelist_ips = ""
            elif "@cn_ipv4" in whitelist_match:
                whitelist_type = "cn"
                whitelist_ips = ""
            elif "{" in whitelist_match:
                whitelist_type = "custom"
                ips_m = re.search(r'\{([^}]*)\}', whitelist_match)
                whitelist_ips = ips_m.group(1).strip() if ips_m else ""
            else:
                whitelist_type = "all"
                whitelist_ips = ""
        else:
            whitelist_type = "all"
            whitelist_ips = ""

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

def _add_nft_rule(text: str, rule: NfRuleCreate) -> str:
    protocols = ["tcp", "udp"] if rule.protocol == "both" else [rule.protocol]
    prefix = _build_whitelist_prefix(rule.whitelist_type, rule.whitelist_ips or "")
    lines = []
    for proto in protocols:
        line = f"        {prefix}{proto} dport {rule.port} dnat to {rule.dest_ip}:{rule.dest_port}"
        if rule.comment:
            line += f" # {rule.comment}"
        lines.append(line)
    idx = text.find("chain prerouting {")
    if idx == -1:
        return text
    close_idx = text.find("\n    }", idx + len("chain prerouting {"))
    if close_idx == -1:
        return text
    return text[:close_idx] + "\n" + "\n".join(lines) + text[close_idx:]

def _remove_nft_rule(text: str, port: int, protocol: str, dest_ip: str, dest_port: int) -> str:
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
    return "\n".join(new_lines)

def _remove_ssl_proxy_nft_rules(text: str) -> str:
    """移除所有由 SSL 代理页面管理的 nftables 规则（input / prerouting 中的标记行）。"""
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        if re.search(r"#\s*ssl-proxy:\d+", line):
            continue
        new_lines.append(line)
    return "\n".join(new_lines)


def _insert_into_chain(text: str, chain_name: str, new_lines: List[str]) -> str:
    """在指定 chain 的结束 '}' 前插入新行。"""
    if not new_lines:
        return text
    marker = f"chain {chain_name} {{"
    idx = text.find(marker)
    if idx == -1:
        return text
    close_idx = text.find("\n    }", idx + len(marker))
    if close_idx == -1:
        return text
    return text[:close_idx] + "\n" + "\n".join(new_lines) + text[close_idx:]

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

def _check_port_conflict(port: int, exclude_rule_id: Optional[int] = None):
    """检查端口是否和 WebUI、现有 SSL 代理规则或防火墙规则冲突。"""
    if port == DMZ_CADDY_PORT:
        raise HTTPException(status_code=400, detail=f"Port {DMZ_CADDY_PORT} is reserved for WebUI")

    ssl_rules = _load_ssl_proxy_rules()
    for r in ssl_rules:
        if r.get("id") == exclude_rule_id:
            continue
        if r["port"] == port:
            raise HTTPException(status_code=400, detail=f"Port {port} is already used by SSL proxy rules")

    # Check firewall rules (ignore ssl-proxy managed rules)
    nft_text = _read_nftables()
    if re.search(rf"^\s*(?:ip\s+saddr\s+(?:!=\s+)?(?:@cn_ipv4|\{{[^}}]*\}})\s+)?\s*(?:tcp|udp)\s+dport\s+{port}\s+dnat\s+to", nft_text, re.MULTILINE):
        # make sure it's not a ssl-proxy rule line
        for line in nft_text.splitlines():
            if re.search(rf"\s+dnat\s+to\s+[0-9.]+:\d+.*#\s*ssl-proxy:{port}", line):
                continue
            if re.search(rf"\s*(?:tcp|udp)\s+dport\s+{port}\s+dnat\s+to", line):
                raise HTTPException(status_code=400, detail=f"Port {port} is already used by firewall rules")

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

        if 'set cn_ipv4 {' in text:
            text = replace_named_block(text, "set cn_ipv4", set_block)
        else:
            idx = text.find('chain prerouting {')
            if idx != -1:
                text = text[:idx] + set_block + '\n\n' + text[idx:]

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
    text = _read_nftables()
    text = _add_nft_rule(text, rule)
    _commit_nftables(text)
    return {"ok": True}

@app.put("/api/nftables/rules/{protocol}/{port}")
def edit_nft_rule(protocol: str, port: int, old_dest_ip: str = Query(...), old_dest_port: int = Query(...), rule: NfRuleCreate = ..., _: str = Depends(verify_token)):
    if rule.port != port:
        raise HTTPException(status_code=400, detail="Port cannot be changed")
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

def _build_caddyfile(rules: Optional[List[dict]] = None) -> str:
    settings = load_settings()
    domain = DMZ_DOMAIN

    if settings.get("https_enabled", True):
        if DMZ_CADDY_TLS_MODE == "auto":
            tls_line = ""
        else:
            tls_line = _tls_line(domain)
    else:
        tls_line = "auto_https off"

    lines = [f"{domain}:{DMZ_CADDY_PORT} {{"]
    lines.append("    encode gzip")
    if tls_line:
        lines.append(f"    {tls_line}")
    lines.append("")

    # WebUI routes only
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
