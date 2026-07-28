#!/bin/bash
set -uo pipefail

# DMZ WebUI 更新脚本
# 用法: sudo ./update.sh
# 功能: 增量更新代码、重新构建、平滑重启、失败自动回滚
# 日志: /var/log/dmz-webui/update-<timestamp>.log

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/dmz-webui"
LOG_DIR="/var/log/dmz-webui"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="$LOG_DIR/update-$TIMESTAMP.log"
ROLLBACK_DIR=""

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

# ----------------- 回滚函数 -----------------
rollback() {
    error "========================================"
    error "更新失败，执行回滚..."
    error "========================================"

    rollback_caddy_changes

    if [ -n "$ROLLBACK_DIR" ] && [ -d "$ROLLBACK_DIR" ]; then
        info "回滚目录: $ROLLBACK_DIR"

        # 停止当前服务
        run_cmd "停止当前服务" systemctl stop dmz-webui

        # 恢复旧版本
        run_cmd "恢复旧版本" rm -rf "$INSTALL_DIR" && cp -a "$ROLLBACK_DIR" "$INSTALL_DIR"

        # 重启服务
        if run_cmd "启动旧版本服务" systemctl start dmz-webui; then
            sleep 2
            if [ "$(systemctl is-active dmz-webui 2>/dev/null || echo "unknown")" = "active" ]; then
                info "回滚成功，服务已恢复运行"
                info "访问地址: http://$(hostname -I | awk '{print $1}'):5000"
            else
                error "回滚后服务未正常运行，请手动排查"
            fi
        else
            error "回滚后服务启动失败，请手动排查"
        fi
    else
        error "未找到回滚备份，无法自动回滚"
    fi

    error "更新日志: $LOG_FILE"
    exit 1
}

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

if [ ! -d "$INSTALL_DIR" ]; then
    echo "[ERROR] $INSTALL_DIR 不存在，请先执行 deploy.sh 进行首次部署"
    exit 1
fi

mkdir -p "$LOG_DIR"

# 加载公共函数并读取/收集配置
source "$SCRIPT_DIR/common.sh"
prompt_config
migrate_ufw

info "========================================"
info "DMZ WebUI 更新开始"
info "源目录: $PROJECT_ROOT"
info "目标目录: $INSTALL_DIR"
info "日志文件: $LOG_FILE"
info "========================================"

# 记录版本信息
CURRENT_GIT=$(cd "$INSTALL_DIR" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
NEW_GIT=$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
info "当前运行版本: $CURRENT_GIT"
info "待更新版本: $NEW_GIT"

if [ "$CURRENT_GIT" = "$NEW_GIT" ] && [ "$CURRENT_GIT" != "unknown" ]; then
    warn "Git 版本号相同，可能没有新代码需要更新"
    warn "如果确认要更新，请继续..."
    sleep 2
fi

# ----------------- Step 1: 创建回滚备份 -----------------
step "1/9 创建回滚备份"

ROLLBACK_DIR="${INSTALL_DIR}.rollback.${TIMESTAMP}"
if run_cmd "备份当前版本到 $ROLLBACK_DIR" cp -a "$INSTALL_DIR" "$ROLLBACK_DIR"; then
    info "回滚备份完成: $ROLLBACK_DIR"
    info "  大小: $(du -sh "$ROLLBACK_DIR" | cut -f1)"
else
    error "回滚备份失败，终止更新"
    exit 1
fi

# 清理旧备份（保留最近5个）
info "清理旧备份..."
ls -1dt "${INSTALL_DIR}".rollback.* 2>/dev/null | tail -n +6 | while read -r old_backup; do
    if [ -d "$old_backup" ]; then
        run_cmd "删除旧备份 $old_backup" rm -rf "$old_backup"
    fi
done

# ----------------- Step 2: 同步代码 -----------------
step "2/9 同步代码"

# 使用 rsync 或 cp 更新代码，保留 venv 和日志
info "同步项目文件（保留 venv、日志、备份）..."

# 先同步到临时目录，避免覆盖过程中服务异常
TEMP_DIR="${INSTALL_DIR}.tmp.${TIMESTAMP}"
run_cmd "创建临时目录" mkdir -p "$TEMP_DIR"
run_cmd "复制新代码到临时目录" cp -r "$PROJECT_ROOT/"* "$TEMP_DIR/"

# 保留运行时需要的数据
for item in venv static logs "${INSTALL_DIR}/.git"; do
    if [ -e "$INSTALL_DIR/$(basename "$item")" ]; then
        info "保留: $item"
        rm -rf "${TEMP_DIR}/$(basename "$item")"
        cp -a "${INSTALL_DIR}/$(basename "$item")" "${TEMP_DIR}/$(basename "$item")" 2>/dev/null || true
    fi
done

# 原子替换
run_cmd "移除旧代码" rm -rf "$INSTALL_DIR"
run_cmd "移动新代码到目标目录" mv "$TEMP_DIR" "$INSTALL_DIR"

info "代码同步完成"
info "  文件数: $(find "$INSTALL_DIR" -type f | wc -l)"

# ----------------- Step 3: 更新 Python 依赖 -----------------
step "3/9 更新 Python 依赖"

cd "$INSTALL_DIR/backend"

ensure_venv() {
    if [ -d "$INSTALL_DIR/venv" ]; then
        if "$INSTALL_DIR/venv/bin/python" --version &>/dev/null; then
            info "虚拟环境可用"
            return 0
        fi
        warn "虚拟环境损坏，重新创建"
        run_cmd "删除损坏的虚拟环境" rm -rf "$INSTALL_DIR/venv"
    fi

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

    error "虚拟环境创建失败"
    return 1
}

if ! ensure_venv; then
    rollback
fi

if [ -f "$INSTALL_DIR/venv/bin/pip" ]; then
    run_cmd "升级 pip" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip --index-url https://pypi.tuna.tsinghua.edu.cn/simple

    # 尝试增量安装，失败则全量重装
    if run_cmd "尝试增量更新 Python 依赖" "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple; then
        info "Python 依赖更新完成"
    else
        warn "增量更新失败，尝试全量重装..."
        run_cmd "删除旧虚拟环境" rm -rf "$INSTALL_DIR/venv"
        if ! ensure_venv; then
            rollback
        fi
        run_cmd "全量安装依赖" "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    fi

    info "已安装包列表:"
    "$INSTALL_DIR/venv/bin/pip" list >> "$LOG_FILE" 2>&1
else
    error "虚拟环境异常"
    rollback
fi

# ----------------- Step 4: 更新前端依赖并构建 -----------------
step "4/9 更新前端依赖并构建"

cd "$INSTALL_DIR/frontend"

if [ ! -f "package.json" ]; then
    error "package.json 不存在"
    rollback
fi

# 检测 package.json 或 package-lock.json 是否变化
PACKAGE_CHANGED=false
if [ -f "$ROLLBACK_DIR/frontend/package.json" ]; then
    if ! diff -q "$ROLLBACK_DIR/frontend/package.json" "$INSTALL_DIR/frontend/package.json" &>/dev/null; then
        PACKAGE_CHANGED=true
        info "package.json 有变化，需要重新安装依赖"
    fi
fi

if [ "$PACKAGE_CHANGED" = true ] || [ ! -d "node_modules" ]; then
    info "执行 npm install..."
    if run_cmd "安装前端依赖" npm install; then
        info "前端依赖安装完成"
    else
        error "前端依赖安装失败"
        rollback
    fi
else
    info "package.json 无变化，跳过 npm install"
fi

if run_cmd "构建前端" npm run build; then
    info "前端构建完成"
    info "  产物大小: $(du -sh "$INSTALL_DIR/frontend/dist" 2>/dev/null | cut -f1 || echo 'unknown')"
else
    error "前端构建失败"
    rollback
fi

# ----------------- Step 5: 配置静态文件 -----------------
step "5/9 配置静态文件"

run_cmd "创建 static 目录" mkdir -p "$INSTALL_DIR/backend/static"
run_cmd "创建 Caddy 静态站点目录" \
    mkdir -p /var/lib/dmz-webui/caddy-static
chmod 755 /var/lib/dmz-webui /var/lib/dmz-webui/caddy-static
SNI_ROUTES_FILE="/etc/dmz-webui/sni_routes.json"
if [ ! -f "$SNI_ROUTES_FILE" ]; then
    echo '[]' > "$SNI_ROUTES_FILE"
    chmod 600 "$SNI_ROUTES_FILE"
    info "TCP/SNI 透传规则文件已初始化: $SNI_ROUTES_FILE"
fi
if run_cmd "复制前端产物" cp -r "$INSTALL_DIR/frontend/dist/"* "$INSTALL_DIR/backend/static/"; then
    info "静态文件配置完成"
else
    error "静态文件复制失败"
    rollback
fi

# 检查后端语法
info "检查后端语法..."
if "$INSTALL_DIR/venv/bin/python" -m py_compile "$INSTALL_DIR/backend/main.py" 2>>"$LOG_FILE"; then
    info "后端语法检查通过"
else
    error "后端语法检查失败"
    rollback
fi

# ----------------- Step 6: 平滑重启服务 -----------------
step "6/9 平滑重启服务"

# 更新 systemd service 文件（如果有变化）
SERVICE_CHANGED=false
if [ -f "$INSTALL_DIR/systemd/dmz-webui.service" ]; then
    if ! diff -q "$INSTALL_DIR/systemd/dmz-webui.service" /etc/systemd/system/dmz-webui.service &>/dev/null; then
        info "systemd service 文件有更新"
        run_cmd "复制新 service 文件" cp "$INSTALL_DIR/systemd/dmz-webui.service" /etc/systemd/system/
        SERVICE_CHANGED=true
    else
        info "systemd service 文件无变化"
    fi
fi

# 刷新 systemd 环境变量覆盖（域名/Caddy 模式等可能已变更）
install_service_override
run_cmd "daemon-reload" systemctl daemon-reload

SVC_STATUS_BEFORE=$(systemctl is-active dmz-webui 2>/dev/null || echo "unknown")
if [ "$SVC_STATUS_BEFORE" = "active" ]; then
    info "服务运行中，执行重启以应用新代码 (restart)..."
    if run_cmd "重启服务" systemctl restart dmz-webui; then
        info "服务重启命令已发送"
    else
        error "服务重启命令失败"
        rollback
    fi
else
    info "服务未运行，执行启动 (start)..."
    if run_cmd "启动服务" systemctl start dmz-webui; then
        info "服务启动命令已发送"
    else
        error "服务启动命令失败"
        rollback
    fi
fi

# 等待服务就绪
info "等待服务就绪 (5s)..."
sleep 5

SVC_STATUS=$(systemctl is-active dmz-webui 2>/dev/null || echo "unknown")
info "服务状态: $SVC_STATUS"

if [ "$SVC_STATUS" != "active" ]; then
    error "服务未正常运行"
    info "最近日志:"
    journalctl -u dmz-webui -n 30 --no-pager >> "$LOG_FILE" 2>&1 || true
    rollback
fi

# Caddy 证书、Caddyfile 与服务
info "检查 Caddy 及证书状态..."

prepare_caddy_rollback
if ! ensure_caddy_layer4; then
    error "Caddy Layer 4 安装或校验失败"
    rollback
fi
if ! ensure_certificate; then
    error "证书准备失败"
    rollback
fi
if ! generate_caddyfile; then
    error "Caddyfile 生成或校验失败"
    rollback
fi

CERT_DIR="/etc/letsencrypt/live/${DMZ_DOMAIN}"
if [ -f "${CERT_DIR}/fullchain.pem" ]; then
    info "修复证书权限..."
    chgrp -R caddy /etc/letsencrypt/live /etc/letsencrypt/archive 2>/dev/null || true
    chmod 750 /etc/letsencrypt/live /etc/letsencrypt/archive 2>/dev/null || true
    find /etc/letsencrypt/live -type f -exec chmod 640 {} \; 2>/dev/null || true
    find /etc/letsencrypt/archive -type f -exec chmod 640 {} \; 2>/dev/null || true
fi

if run_cmd "重启 Caddy" systemctl restart caddy; then
    sleep 2
    if [ "$(systemctl is-active caddy 2>/dev/null || echo "unknown")" = "active" ]; then
        info "Caddy 运行正常"
    else
        warn "Caddy 启动后状态异常"
    fi
else
    error "Caddy 重启失败"
    rollback
fi

# 根据 Caddy 模式配置 nftables 基础规则
configure_nftables_base

# ----------------- Step 7: 确保 nftables 配置生效 -----------------
step "7/9 确保 nftables 配置生效"

SYNC_SCRIPT="$INSTALL_DIR/scripts/sync_nftables.py"
APPLY_SCRIPT="$INSTALL_DIR/scripts/apply_nftables.py"

if [ -f "$SYNC_SCRIPT" ]; then
    info "同步 nftables 配置（保留用户自定义规则与 SSL 代理规则）..."
    if run_cmd "同步 nftables 配置" python3 "$SYNC_SCRIPT"; then
        info "nftables 配置同步完成"
    else
        error "nftables 配置同步失败"
        rollback
    fi
else
    error "未找到同步脚本 $SYNC_SCRIPT"
    rollback
fi

# 只应用 DMZ WebUI 独占表；禁止重启 nftables 或完整加载全局规则集
if [ -f "$APPLY_SCRIPT" ]; then
    if run_cmd "定向应用 DMZ WebUI nftables 规则" python3 "$APPLY_SCRIPT" --migrate-legacy; then
        info "DMZ WebUI nftables 规则已生效，外部表未重载"
    else
        error "DMZ WebUI nftables 规则应用失败"
        rollback
    fi
else
    error "未找到定向应用脚本 $APPLY_SCRIPT"
    rollback
fi

# 只设置开机自启；运行时不得重启 nftables，以免影响 Docker/外部规则
if run_cmd "启用 nftables 开机自启" systemctl enable nftables; then
    info "nftables 开机自启已启用"
fi

# ----------------- Step 8: 检查并持久化 IP 转发 -----------------
step "8/9 检查并持久化 IP 转发"

SYSCTL_FILE="/etc/sysctl.d/99-dmz-webui-forwarding.conf"

IPV4_FORWARD=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo "0")
if [ "$IPV4_FORWARD" != "1" ]; then
    info "启用 IPv4 转发..."
    echo 1 > /proc/sys/net/ipv4/ip_forward
    info "IPv4 转发已启用"
else
    info "IPv4 转发已开启"
fi

IPV6_FORWARD=$(cat /proc/sys/net/ipv6/conf/all/forwarding 2>/dev/null || echo "0")
if [ "$IPV6_FORWARD" != "1" ]; then
    info "启用 IPv6 转发..."
    echo 1 > /proc/sys/net/ipv6/conf/all/forwarding
    info "IPv6 转发已启用"
else
    info "IPv6 转发已开启"
fi

# 持久化到 sysctl.d，确保重启后转发保持开启
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

# ----------------- Step 9: 健康检查与验证 -----------------
step "9/9 健康检查与验证"

HEALTH_CHECK_URL="http://127.0.0.1:5000/api/status"
MAX_RETRY=5
RETRY=0
HEALTH_STATUS="000"

while [ "$RETRY" -lt "$MAX_RETRY" ]; do
    HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_CHECK_URL" 2>/dev/null || echo "000")
    if [ "$HEALTH_STATUS" = "200" ]; then
        break
    fi
    RETRY=$((RETRY + 1))
    info "健康检查重试 ($RETRY/$MAX_RETRY)..."
    sleep 2
done

if [ "$HEALTH_STATUS" = "200" ]; then
    HEALTH_BODY=$(curl -s "$HEALTH_CHECK_URL" 2>/dev/null || echo "unknown")
    info "健康检查通过: HTTP $HEALTH_STATUS"
    info "响应内容: $HEALTH_BODY"
else
    error "健康检查失败: HTTP $HEALTH_STATUS"
    info "最近日志:"
    journalctl -u dmz-webui -n 30 --no-pager >> "$LOG_FILE" 2>&1 || true
    rollback
fi

# 检查关键页面可访问
for path in "/" "/login"; do
    PAGE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5000${path}" 2>/dev/null || echo "000")
    info "页面检查 $path: HTTP $PAGE_STATUS"
done

# ----------------- 更新完成 -----------------
info "========================================"
info "DMZ WebUI 更新完成"
info "========================================"
if [ "${CADDY_MODE:-non443}" = "standard" ]; then
    info "访问地址: https://${DMZ_DOMAIN}/admin"
else
    info "访问地址: https://${DMZ_DOMAIN}:8443/admin"
fi
info "日志文件: $LOG_FILE"
info "回滚备份: $ROLLBACK_DIR"
info ""
info "管理命令:"
info "  systemctl status dmz-webui"
info "  systemctl restart dmz-webui"
info "  journalctl -u dmz-webui -f"
info "  tail -f $LOG_FILE"
info ""
info "如需回滚到旧版本:"
info "  sudo rm -rf $INSTALL_DIR && sudo cp -a $ROLLBACK_DIR $INSTALL_DIR && sudo systemctl restart dmz-webui"
info "========================================"

exit 0
