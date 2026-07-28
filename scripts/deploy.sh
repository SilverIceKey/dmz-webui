#!/bin/bash
set -uo pipefail

# DMZ WebUI 部署脚本
# 用法: sudo ./deploy.sh
# 日志: /var/log/dmz-webui/deploy-<timestamp>.log

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/dmz-webui"
LOG_DIR="/var/log/dmz-webui"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/deploy-$TIMESTAMP.log"

# ----------------- 日志函数 -----------------
log() {
    local level="$1"
    shift
    local msg="$(date '+%Y-%m-%d %H:%M:%S') [$level] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

info()  { log "INFO"  "$@"; }
warn()  { log "WARN"  "$@"; }
error() { log "ERROR" "$@"; }
step()  { log "STEP"  "======================================== [$1]"; }

# 带日志的命令执行
run_cmd() {
    local desc="$1"
    shift
    info "执行: $desc"
    info "命令: $*"
    if "$@" >> "$LOG_FILE" 2>&1; then
        info "成功: $desc"
        return 0
    else
        local ret=$?
        error "失败: $desc (exit=$ret)"
        return $ret
    fi
}

# ----------------- 初始化检查 -----------------
if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] 请使用 sudo 或 root 用户运行此脚本"
    exit 1
fi

mkdir -p "$LOG_DIR"

# 加载公共函数并交互式收集配置
source "$SCRIPT_DIR/common.sh"
prompt_config
migrate_ufw

info "========================================"
info "DMZ WebUI 部署开始"
info "源目录: $PROJECT_ROOT"
info "目标目录: $INSTALL_DIR"
info "日志文件: $LOG_FILE"
info "========================================"

# 记录环境信息
info "环境信息:"
info "  OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
info "  Kernel: $(uname -r)"
info "  Hostname: $(hostname)"
info "  当前用户: $(whoami)"
info "  源目录 Git 版本: $(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo '非Git目录')"

# ----------------- Step 1: 安装系统依赖 -----------------
step "1/7 安装系统依赖"

# 检查必要命令/模块是否存在
MISSING_PKGS=()

for cmd in python3 npm nft caddy curl systemctl; do
    if ! command -v "$cmd" &>/dev/null; then
        warn "命令缺失: $cmd"
        case "$cmd" in
            python3) MISSING_PKGS+=(python3 python3-venv python3-dev) ;;
            npm) MISSING_PKGS+=(nodejs npm) ;;
            nft) MISSING_PKGS+=(nftables) ;;
            caddy) MISSING_PKGS+=(caddy) ;;
            curl) MISSING_PKGS+=(curl) ;;
            systemctl) warn "systemctl 不存在，可能是容器环境" ;;
        esac
    else
        info "命令检查通过: $cmd ($($cmd --version 2>/dev/null | head -1 || echo 'version unknown'))"
    fi
done

# 单独检查 python3 venv 模块（Debian 可能分包装）
if command -v python3 &>/dev/null; then
    if ! python3 -m venv --help &>/dev/null; then
        warn "python3 venv 模块不可用"
        # 尝试匹配当前 Python 版本的 venv 包
        PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        MISSING_PKGS+=("python${PY_VER}-venv")
    else
        info "python3 venv 模块检查通过"
    fi
fi

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    info "尝试安装缺失包: ${MISSING_PKGS[*]}"
    if run_cmd "apt-get update" apt-get update; then
        if run_cmd "安装依赖包" apt-get install -y "${MISSING_PKGS[@]}" libpam0g-dev build-essential; then
            info "系统依赖安装完成"
        else
            error "系统依赖安装失败，继续尝试后续步骤..."
        fi
    else
        error "apt-get update 失败"
    fi
else
    info "所有系统依赖已存在，跳过安装"
fi

# ----------------- Step 2: 备份旧版本 -----------------
step "2/7 备份旧版本"

if [ -d "$INSTALL_DIR" ]; then
    BACKUP_DIR="${INSTALL_DIR}.backup.${TIMESTAMP}"
    if run_cmd "备份旧版本到 $BACKUP_DIR" cp -a "$INSTALL_DIR" "$BACKUP_DIR"; then
        info "旧版本备份完成: $BACKUP_DIR"
    else
        warn "旧版本备份失败，继续部署..."
    fi
else
    info "首次部署，无需备份"
fi

# ----------------- Step 3: 复制项目文件 -----------------
step "3/7 复制项目文件"

if run_cmd "创建目标目录" mkdir -p "$INSTALL_DIR"; then
    info "目标目录就绪"
fi

# 清理旧内容（保留备份）
if [ -d "$INSTALL_DIR" ]; then
    run_cmd "清理旧内容" rm -rf "${INSTALL_DIR:?}"
fi

if run_cmd "复制项目文件" cp -r "$PROJECT_ROOT" "$INSTALL_DIR"; then
    info "项目文件复制完成"
    info "  文件数: $(find "$INSTALL_DIR" -type f | wc -l)"
    info "  总大小: $(du -sh "$INSTALL_DIR" | cut -f1)"
else
    error "项目文件复制失败"
    exit 1
fi

# ----------------- Step 4: 安装 Python 依赖 -----------------
step "4/7 安装 Python 依赖"

if [ ! -f "$INSTALL_DIR/backend/requirements.txt" ]; then
    error "requirements.txt 不存在"
    exit 1
fi

cd "$INSTALL_DIR/backend"

ensure_venv() {
    if [ -d "$INSTALL_DIR/venv" ]; then
        info "发现已有虚拟环境，尝试复用..."
        if "$INSTALL_DIR/venv/bin/python" --version &>/dev/null; then
            info "虚拟环境可用，跳过创建"
            return 0
        else
            warn "虚拟环境损坏，重新创建"
            run_cmd "删除损坏的虚拟环境" rm -rf "$INSTALL_DIR/venv"
        fi
    fi

    info "创建 Python 虚拟环境..."
    if python3 -m venv "$INSTALL_DIR/venv" >> "$LOG_FILE" 2>&1; then
        info "虚拟环境创建成功"
        return 0
    fi

    warn "venv 创建失败，尝试安装 python3-venv 包..."
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if run_cmd "安装 python${PY_VER}-venv" apt-get install -y "python${PY_VER}-venv"; then
        if python3 -m venv "$INSTALL_DIR/venv" >> "$LOG_FILE" 2>&1; then
            info "虚拟环境创建成功（重试后）"
            return 0
        fi
    fi

    error "虚拟环境创建失败，请手动检查 python3-venv 是否可用"
    return 1
}

if ! ensure_venv; then
    exit 1
fi

if [ -f "$INSTALL_DIR/venv/bin/pip" ]; then
    run_cmd "升级 pip" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    if run_cmd "安装 Python 依赖" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" --index-url https://pypi.tuna.tsinghua.edu.cn/simple; then
        info "Python 依赖安装完成"
        info "已安装包列表:"
        "$INSTALL_DIR/venv/bin/pip" list >> "$LOG_FILE" 2>&1
    else
        error "Python 依赖安装失败"
        exit 1
    fi
else
    error "虚拟环境创建失败，pip 不存在"
    exit 1
fi

# ----------------- Step 5: 构建前端 -----------------
step "5/7 构建前端"

cd "$INSTALL_DIR/frontend"

if [ ! -f "package.json" ]; then
    error "package.json 不存在"
    exit 1
fi

if run_cmd "安装前端依赖" npm install; then
    info "前端依赖安装完成"
    info "  node_modules 大小: $(du -sh node_modules 2>/dev/null | cut -f1 || echo 'unknown')"
else
    error "前端依赖安装失败"
    exit 1
fi

if run_cmd "构建前端" npm run build; then
    info "前端构建完成"
    if [ -d "$INSTALL_DIR/frontend/dist" ]; then
        info "  构建产物: $(du -sh "$INSTALL_DIR/frontend/dist" | cut -f1)"
        info "  文件数: $(find "$INSTALL_DIR/frontend/dist" -type f | wc -l)"
    else
        warn "构建产物目录 dist 不存在"
    fi
else
    error "前端构建失败"
    exit 1
fi

# ----------------- Step 6: 配置静态文件与服务 -----------------
step "6/7 配置静态文件与 systemd"

# 复制静态文件
if [ -d "$INSTALL_DIR/frontend/dist" ]; then
    run_cmd "创建 static 目录" mkdir -p "$INSTALL_DIR/backend/static"
    if run_cmd "复制前端产物到 static" cp -r "$INSTALL_DIR/frontend/dist/"* "$INSTALL_DIR/backend/static/"; then
        info "静态文件配置完成"
    else
        error "静态文件复制失败"
        exit 1
    fi
else
    error "前端构建产物不存在，无法配置静态文件"
    exit 1
fi

# 确保 main.py 中静态文件挂载已存在（当前版本已内置，此处为兼容旧版本）
if ! grep -q "StaticFiles" "$INSTALL_DIR/backend/main.py"; then
    warn "main.py 缺少 StaticFiles 导入，自动修复..."
    sed -i '1i\from fastapi.staticfiles import StaticFiles' "$INSTALL_DIR/backend/main.py"
    sed -i '/if __name__/i\\napp.mount("/", StaticFiles(directory="static", html=True), name="static")' "$INSTALL_DIR/backend/main.py"
    info "已自动修复 StaticFiles 导入"
fi

# 初始化 SSL 代理规则文件
SSL_PROXY_RULES_FILE="/etc/dmz-webui/ssl_proxy_rules.json"
if [ ! -f "$SSL_PROXY_RULES_FILE" ]; then
    run_cmd "初始化 SSL 代理规则文件" mkdir -p /etc/dmz-webui
    echo '[]' > "$SSL_PROXY_RULES_FILE"
    info "SSL 代理规则文件已初始化: $SSL_PROXY_RULES_FILE"
else
    info "SSL 代理规则文件已存在，跳过初始化"
fi

SITE_ROUTES_FILE="/etc/dmz-webui/site_routes.json"
if [ ! -f "$SITE_ROUTES_FILE" ]; then
    echo '[]' > "$SITE_ROUTES_FILE"
    chmod 600 "$SITE_ROUTES_FILE"
    info "站点路由规则文件已初始化: $SITE_ROUTES_FILE"
fi
SNI_ROUTES_FILE="/etc/dmz-webui/sni_routes.json"
if [ ! -f "$SNI_ROUTES_FILE" ]; then
    echo '[]' > "$SNI_ROUTES_FILE"
    chmod 600 "$SNI_ROUTES_FILE"
    info "TCP/SNI 透传规则文件已初始化: $SNI_ROUTES_FILE"
fi
run_cmd "创建 Caddy 静态站点目录" \
    mkdir -p /var/lib/dmz-webui/caddy-static
chmod 755 /var/lib/dmz-webui /var/lib/dmz-webui/caddy-static

# 检查后端语法
info "检查后端语法..."
if "$INSTALL_DIR/venv/bin/python" -m py_compile "$INSTALL_DIR/backend/main.py" 2>>"$LOG_FILE"; then
    info "后端语法检查通过"
else
    error "后端语法检查失败"
    exit 1
fi

# 注册 systemd 服务
SERVICE_FILE="/etc/systemd/system/dmz-webui.service"
if run_cmd "复制 systemd service 文件" cp "$INSTALL_DIR/systemd/dmz-webui.service" "$SERVICE_FILE"; then
    info "service 文件已注册: $SERVICE_FILE"
else
    error "systemd service 文件复制失败"
    exit 1
fi

# 写入 systemd 环境变量覆盖，确保后端能读取 DMZ_DOMAIN/CADDY_PORT 等
install_service_override

# 重新加载 systemd
if run_cmd "systemctl daemon-reload" systemctl daemon-reload; then
    info "systemd 重新加载完成"
fi

# 启用开机自启
if run_cmd "启用开机自启" systemctl enable dmz-webui; then
    info "开机自启已启用"
fi

# 启动/重启服务
info "正在重启 dmz-webui 服务..."
if systemctl is-active --quiet dmz-webui 2>/dev/null; then
    if run_cmd "重启服务" systemctl restart dmz-webui; then
        info "服务已重启"
    else
        error "服务重启失败"
        exit 1
    fi
else
    if run_cmd "启动服务" systemctl start dmz-webui; then
        info "服务已启动"
    else
        error "服务启动失败"
        exit 1
    fi
fi

# 等待服务就绪
info "等待服务就绪 (3s)..."
sleep 3

# 服务状态检查
SVC_STATUS=$(systemctl is-active dmz-webui 2>/dev/null || echo "unknown")
SVC_STATUS_DETAIL=$(systemctl status dmz-webui --no-pager 2>&1 || true)
info "服务状态: $SVC_STATUS"
info "服务详情:"
echo "$SVC_STATUS_DETAIL" | while read -r line; do
    info "  $line"
done

if [ "$SVC_STATUS" != "active" ]; then
    error "服务未正常运行 (status=$SVC_STATUS)"
    info "查看日志: journalctl -u dmz-webui -n 50 --no-pager"
    exit 1
fi

# 健康检查
info "执行健康检查..."
HEALTH_CHECK_URL="http://127.0.0.1:5000/api/status"
HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_CHECK_URL" 2>/dev/null || echo "000")
if [ "$HEALTH_STATUS" = "200" ]; then
    HEALTH_BODY=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null || echo "unknown")
    info "健康检查通过: HTTP $HEALTH_STATUS"
    info "响应内容: $HEALTH_BODY"
else
    error "健康检查失败: HTTP $HEALTH_STATUS"
    info "尝试查看最近日志:"
    journalctl -u dmz-webui -n 20 --no-pager >> "$LOG_FILE" 2>&1 || true
    exit 1
fi

# ----------------- Step 7: 启用 IP 转发 -----------------
step "7/9 启用 IP 转发"

SYSCTL_FILE="/etc/sysctl.d/99-dmz-webui-forwarding.conf"

IPV4_FORWARD=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo "0")
if [ "$IPV4_FORWARD" != "1" ]; then
    info "启用 IPv4 转发..."
    echo 1 > /proc/sys/net/ipv4/ip_forward
    info "IPv4 转发已启用"
else
    info "IPv4 转发已开启，跳过"
fi

IPV6_FORWARD=$(cat /proc/sys/net/ipv6/conf/all/forwarding 2>/dev/null || echo "0")
if [ "$IPV6_FORWARD" != "1" ]; then
    info "启用 IPv6 转发..."
    echo 1 > /proc/sys/net/ipv6/conf/all/forwarding
    info "IPv6 转发已启用"
else
    info "IPv6 转发已开启，跳过"
fi

# 持久化到 sysctl.d，优先级高于 /etc/sysctl.conf，且不会被其他工具覆盖
info "写入 IP 转发持久化配置: $SYSCTL_FILE"
tee "$SYSCTL_FILE" > /dev/null <<'EOF'
# DMZ WebUI: enable IPv4/IPv6 forwarding for NAT/DNAT
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF

if command -v sysctl >/dev/null 2>&1; then
    if run_cmd "应用 sysctl 配置" sysctl -p "$SYSCTL_FILE"; then
        info "sysctl 配置已应用"
    else
        warn "sysctl 应用失败，请手动检查"
    fi
else
    warn "sysctl 命令未找到，已写入配置文件，重启后生效"
fi

# ----------------- Step 8: SSL 证书与 Caddy 配置 -----------------
step "8/9 SSL 证书与 Caddy 配置"

prepare_caddy_rollback
if ! ensure_caddy_layer4; then
    error "Caddy Layer 4 安装或校验失败"
    rollback_caddy_changes
    exit 1
fi
if ! ensure_certificate; then
    error "证书准备失败"
    rollback_caddy_changes
    exit 1
fi
if ! generate_caddyfile; then
    error "Caddyfile 生成或校验失败"
    rollback_caddy_changes
    exit 1
fi

# 修复证书权限（如适用）
CERT_DIR="/etc/letsencrypt/live/${DMZ_DOMAIN}"
if [ -f "${CERT_DIR}/fullchain.pem" ]; then
    info "修复证书权限..."
    chgrp -R caddy /etc/letsencrypt/live /etc/letsencrypt/archive 2>/dev/null || true
    chmod 750 /etc/letsencrypt/live /etc/letsencrypt/archive 2>/dev/null || true
    find /etc/letsencrypt/live -type f -exec chmod 640 {} \; 2>/dev/null || true
    find /etc/letsencrypt/archive -type f -exec chmod 640 {} \; 2>/dev/null || true
fi

# 重启 Caddy
if run_cmd "重启 Caddy" systemctl restart caddy; then
    sleep 2
    if [ "$(systemctl is-active caddy 2>/dev/null || echo "unknown")" = "active" ]; then
        info "Caddy 运行正常"
    else
        warn "Caddy 启动后状态异常"
    fi
else
    error "Caddy 重启失败，恢复部署前配置"
    rollback_caddy_changes
    exit 1
fi

# 根据 Caddy 模式配置 nftables 基础规则（替换占位符、放行对应端口）
configure_nftables_base

# ----------------- Step 9: nftables 放行 -----------------
step "9/9 nftables 放行"

SYNC_SCRIPT="$INSTALL_DIR/scripts/sync_nftables.py"
APPLY_SCRIPT="$INSTALL_DIR/scripts/apply_nftables.py"

if [ -f "$SYNC_SCRIPT" ]; then
    info "同步 nftables 配置（保留用户自定义规则与 SSL 代理规则）..."
    if run_cmd "同步 nftables 配置" python3 "$SYNC_SCRIPT"; then
        info "nftables 配置同步完成"
    else
        error "nftables 配置同步失败，终止部署以避免运行态与持久化配置不一致"
        exit 1
    fi
else
    error "未找到同步脚本 $SYNC_SCRIPT"
    exit 1
fi

# 只应用 DMZ WebUI 独占表；禁止重启 nftables 或完整加载全局规则集
if [ -f "$APPLY_SCRIPT" ]; then
    if run_cmd "定向应用 DMZ WebUI nftables 规则" python3 "$APPLY_SCRIPT" --migrate-legacy; then
        info "DMZ WebUI nftables 规则已生效，外部表未重载"
    else
        error "DMZ WebUI nftables 规则应用失败"
        exit 1
    fi
else
    error "未找到定向应用脚本 $APPLY_SCRIPT"
    exit 1
fi

# 只设置开机自启；运行时不得重启 nftables，以免影响 Docker/外部规则
if run_cmd "启用 nftables 开机自启" systemctl enable nftables; then
    info "nftables 开机自启已启用"
fi

# ----------------- 部署完成汇总 -----------------
info "========================================"
info "DMZ WebUI 部署完成"
info "========================================"
if [ "${CADDY_MODE:-non443}" = "standard" ]; then
    info "访问地址: https://${DMZ_DOMAIN}/admin"
else
    info "访问地址: https://${DMZ_DOMAIN}:8443/admin"
fi
info "日志文件: $LOG_FILE"
info "备份目录: ${INSTALL_DIR}.backup.${TIMESTAMP:-无}"
info ""
info "管理命令:"
info "  systemctl status dmz-webui"
info "  systemctl restart dmz-webui"
info "  journalctl -u dmz-webui -f"
info "  tail -f $LOG_FILE"
info ""
info "如需更新，请使用 scripts/update.sh"
info "========================================"

exit 0
