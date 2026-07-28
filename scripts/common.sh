#!/bin/bash
# DMZ WebUI deploy/update 公共函数
# 由 deploy.sh / update.sh source 使用

CONFIG_FILE="/etc/dmz-webui/install.conf"

# -------------- 配置收集与持久化 --------------

validate_domain() {
    local d="$1"
    [[ -n "$d" ]] && [[ "$d" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$ ]]
}

validate_icp_number() {
    local value="$1"
    [[ -z "$value" ]] || [[ "$value" =~ ^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]ICP备[0-9]+号(-[0-9]+)?$ ]]
}

validate_title() {
    local value="$1"
    if [[ -z "$value" || ${#value} -gt 80 ]]; then
        return 1
    fi
    case "$value" in
        *"'"*|*'"'*|*\\*)
            return 1
            ;;
    esac
    ! printf '%s' "$value" | LC_ALL=C grep -q '[[:cntrl:]]'
}

prompt_title_config() {
    local variable_name="$1"
    local label="$2"
    local current_value="${!variable_name:-DMZ WebUI}"
    local input

    while true; do
        read -rp "请输入${label} [${current_value}]（输入 - 恢复默认）: " input
        input="${input#"${input%%[![:space:]]*}"}"
        input="${input%"${input##*[![:space:]]}"}"
        if [[ "$input" == "-" ]]; then
            input="DMZ WebUI"
        else
            input="${input:-$current_value}"
        fi
        if validate_title "$input"; then
            printf -v "$variable_name" '%s' "$input"
            return 0
        fi
        warn "${label}必须为 1-80 个可打印字符，且不能包含引号或反斜杠"
    done
}

mask_domain() {
    local d="$1"
    if [[ -z "$d" || "$d" == "example.com" ]]; then
        echo "未配置"
        return
    fi
    # 保留首段前两位和最后一段，中间脱敏
    local prefix suffix
    prefix="${d:0:2}"
    suffix="${d##*.}"
    echo "${prefix}***.${suffix}"
}

load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        # shellcheck source=/dev/null
        set -a
        # shellcheck source=/dev/null
        source "$CONFIG_FILE"
        set +a
        return 0
    fi
    return 1
}

save_config() {
    mkdir -p "$(dirname "$CONFIG_FILE")"
    cat > "$CONFIG_FILE" <<EOF
# DMZ WebUI 部署配置（由 scripts/deploy.sh / scripts/update.sh 生成）
# 时间戳: $(date '+%Y-%m-%d %H:%M:%S')
DMZ_DOMAIN='${DMZ_DOMAIN}'
DMZ_WEBUI_HOST='${DMZ_WEBUI_HOST:-127.0.0.1}'
CADDY_MODE='${CADDY_MODE:-non443}'
DMZ_CADDY_PORT='${DMZ_CADDY_PORT:-8443}'
DMZ_CADDY_TLS_MODE='${DMZ_CADDY_TLS_MODE:-manual}'
DMZ_ICP_NUMBER='${DMZ_ICP_NUMBER:-}'
DMZ_SITE_TITLE='${DMZ_SITE_TITLE:-DMZ WebUI}'
DMZ_TAB_TITLE='${DMZ_TAB_TITLE:-DMZ WebUI}'
ACME_EMAIL='${ACME_EMAIL:-}'
EOF
    chmod 600 "$CONFIG_FILE"
    info "部署配置已保存: $CONFIG_FILE（域名已脱敏: $(mask_domain "$DMZ_DOMAIN")）"
}

prompt_public_caddy_config() {
    local domain_default="${DMZ_DOMAIN:-}"
    local domain_input
    while true; do
        if [[ -n "$domain_default" ]]; then
            read -rp "请输入公网域名 [${domain_default}]: " domain_input
            DMZ_DOMAIN="${domain_input:-$domain_default}"
        else
            read -rp "请输入公网域名 (例如 home.example.com): " DMZ_DOMAIN
        fi
        if validate_domain "$DMZ_DOMAIN"; then
            break
        fi
        warn "域名格式不正确，请重新输入"
        domain_default=""
    done

    echo ""
    echo "请选择 Caddy 部署模式："
    echo "  1) 标准 443 端口 + Caddy 自动 HTTPS（需要域名已解析到本机，且 80/443 端口可达）"
    echo "  2) 非 443 端口 8443 + Let's Encrypt DNS 证书 / 自签名（当前方式，443 被封锁或不方便暴露时使用）"
    local mode_choice mode_default
    if [[ "${CADDY_MODE:-non443}" == "standard" ]]; then
        mode_default=1
    else
        mode_default=2
    fi
    read -rp "选项 [1/2，默认 ${mode_default}]: " mode_choice
    case "${mode_choice:-$mode_default}" in
        1)
            CADDY_MODE="standard"
            DMZ_CADDY_PORT=443
            DMZ_CADDY_TLS_MODE="auto"
            ;;
        2|*)
            CADDY_MODE="non443"
            DMZ_CADDY_PORT=8443
            DMZ_CADDY_TLS_MODE="manual"
            ;;
    esac
    info "已选择 Caddy 模式: $CADDY_MODE (端口: $DMZ_CADDY_PORT)"

    if [[ "$CADDY_MODE" == "standard" ]]; then
        local acme_default="${ACME_EMAIL:-}"
        local acme_input
        read -rp "请输入 ACME 邮箱 [${acme_default:-留空由 Caddy 自动处理}]（输入 - 清空）: " acme_input
        if [[ "$acme_input" == "-" ]]; then
            ACME_EMAIL=""
        else
            ACME_EMAIL="${acme_input:-$acme_default}"
        fi
        if [[ -n "$ACME_EMAIL" && ! "$ACME_EMAIL" =~ ^[^@]+@[^@]+\.[^@]+$ ]]; then
            warn "邮箱格式不正确，已忽略"
            ACME_EMAIL=""
        fi
    else
        ACME_EMAIL=""
    fi

    CF_API_KEY=""
    CF_EMAIL=""
    if [[ "$CADDY_MODE" == "non443" ]]; then
        local use_cf
        read -rp "是否使用 Cloudflare DNS 申请 Let's Encrypt 证书? [y/N]: " use_cf
        if [[ "${use_cf:-N}" =~ ^[Yy]$ ]]; then
            read -rsp "请输入 Cloudflare API Key: " CF_API_KEY
            echo ""
            read -rp "请输入 Cloudflare 邮箱: " CF_EMAIL
            if [[ -z "$CF_API_KEY" || -z "$CF_EMAIL" ]]; then
                warn "未提供完整的 Cloudflare 凭证，将使用自签名证书"
                CF_API_KEY=""
                CF_EMAIL=""
            fi
        fi
    fi

    local host_input
    read -rp "请输入 WebUI 后端监听地址 [${DMZ_WEBUI_HOST:-127.0.0.1}]: " host_input
    DMZ_WEBUI_HOST="${host_input:-${DMZ_WEBUI_HOST:-127.0.0.1}}"
}

prompt_branding_config() {
    prompt_title_config DMZ_SITE_TITLE "站点标题"
    prompt_title_config DMZ_TAB_TITLE "浏览器页签标题"
}

prompt_icp_config() {
    local icp_default="${DMZ_ICP_NUMBER:-}"
    local icp_input
    while true; do
        if [[ -n "$icp_default" ]]; then
            read -rp "请输入 ICP 备案号 [${icp_default}]（输入 - 清空）: " icp_input
            if [[ "$icp_input" == "-" ]]; then
                DMZ_ICP_NUMBER=""
            else
                DMZ_ICP_NUMBER="${icp_input:-$icp_default}"
            fi
        else
            read -rp "请输入 ICP 备案号（可选，留空不显示，例如：浙ICP备12345678号）: " DMZ_ICP_NUMBER
        fi
        if validate_icp_number "$DMZ_ICP_NUMBER"; then
            break
        fi
        warn "ICP备案号格式不正确，请重新输入"
        icp_default=""
    done
}

confirm_config_group() {
    local prompt="$1"
    local answer
    read -rp "$prompt [y/N]: " answer
    [[ "${answer:-N}" =~ ^[Yy]$ ]]
}

prompt_config() {
    if load_config; then
        info "检测到已有部署配置: $(mask_domain "$DMZ_DOMAIN")"

        if confirm_config_group "是否修改公网与 Caddy 配置？"; then
            prompt_public_caddy_config
        else
            info "保留现有公网与 Caddy 配置"
        fi

        if confirm_config_group "是否修改页面标题配置？"; then
            prompt_branding_config
        else
            info "保留现有页面标题配置"
        fi

        if confirm_config_group "是否修改备案配置？"; then
            prompt_icp_config
        else
            info "保留现有备案配置"
        fi

        save_config
        return 0
    fi

    info "未检测到部署配置，开始收集全部配置..."
    prompt_public_caddy_config
    prompt_branding_config
    prompt_icp_config
    save_config
}

# -------------- nftables 基础配置 --------------

detect_ssh_ports() {
    local ports
    ports=$(ss -tlnp 2>/dev/null | awk '/sshd/ {
        n = split($4, a, ":")
        print a[n]
    }' | sort -u | awk '{if(NR==1) out=$1; else out=out", "$1} END{print out}')
    if [[ -n "$ports" ]]; then
        echo "$ports"
    else
        echo "22"
    fi
}

detect_wan_iface() {
    local iface
    iface=$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')
    if [[ -n "$iface" ]]; then
        echo "$iface"
    else
        echo "eth0"
    fi
}

configure_nftables_base() {
    local base_file="${INSTALL_DIR:?}/configs/nftables.conf"
    if [[ ! -f "$base_file" ]]; then
        warn "未找到 nftables 基础配置: $base_file"
        return 1
    fi

    local ssh_ports wan_iface
    ssh_ports=$(detect_ssh_ports)
    wan_iface=$(detect_wan_iface)

    # 替换占位符
    sed -i -e "s/<SSH_PORT>/${ssh_ports}/g" -e "s/<WAN_INTERFACE>/${wan_iface}/g" "$base_file"

    # 根据 Caddy 模式调整 input 链放行端口
    if [[ "${CADDY_MODE:-non443}" == "standard" ]]; then
        sed -i 's/^\( *\)tcp dport 8443 accept/\1tcp dport 80 accept\n\1tcp dport 443 accept/' "$base_file"
        info "nftables input 链已调整为放行 80/443（标准 443 模式）"
    else
        info "nftables input 链保持放行 8443（非 443 模式）"
    fi

    info "nftables 基础占位符已替换: SSH_PORTS=${ssh_ports}, WAN_IFACE=${wan_iface}"
}

# -------------- 证书申请 --------------

ensure_certificate() {
    USE_LE_CERT=0
    CERT_DOMAIN="${DMZ_DOMAIN}"
    CERT_DIR="/etc/letsencrypt/live/${CERT_DOMAIN}"

    if [[ "${CADDY_MODE:-non443}" == "standard" ]]; then
        info "标准 443 模式由 Caddy 自动处理 HTTPS 证书，跳过 certbot 申请"
        USE_LE_CERT=0
        return 0
    fi

    if [[ -f "${CERT_DIR}/fullchain.pem" ]] && [[ -f "${CERT_DIR}/privkey.pem" ]]; then
        info "Let's Encrypt 证书已存在，跳过签发"
        USE_LE_CERT=1
        return 0
    fi

    if [[ -n "${CF_API_KEY:-}" ]] && [[ -n "${CF_EMAIL:-}" ]]; then
        info "尝试使用 Cloudflare DNS 签发 Let's Encrypt 证书..."

        if ! command -v certbot &>/dev/null; then
            run_cmd "安装 certbot 及 Cloudflare 插件" apt-get install -y certbot python3-certbot-dns-cloudflare
        fi

        mkdir -p /etc/letsencrypt
        tee /etc/letsencrypt/cloudflare.ini > /dev/null <<CFEOF
dns_cloudflare_email = ${CF_EMAIL}
dns_cloudflare_api_key = ${CF_API_KEY}
CFEOF
        chmod 600 /etc/letsencrypt/cloudflare.ini

        # 注意：不通过 run_cmd 记录完整命令，避免 API Key 进入日志
        info "执行 certbot certonly --dns-cloudflare ..."
        if certbot certonly --dns-cloudflare --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
            -d "${CERT_DOMAIN}" --agree-tos -m "${CF_EMAIL}" --non-interactive >> "$LOG_FILE" 2>&1; then
            info "证书签发成功"
            USE_LE_CERT=1
        else
            warn "证书签发失败，将使用自签名证书"
            USE_LE_CERT=0
        fi
    else
        info "未提供 Cloudflare 凭证，使用自签名证书"
        USE_LE_CERT=0
    fi
}

# -------------- Caddyfile 生成 --------------

generate_caddyfile() {
    local generator="${INSTALL_DIR:?}/scripts/generate_caddyfile.py"
    local python_bin="${INSTALL_DIR}/venv/bin/python"
    local site="${DMZ_DOMAIN}:${DMZ_CADDY_PORT:-8443}"
    local mode="${CADDY_MODE:-non443}"

    info "生成完整 Caddyfile（站点: $(mask_domain "$site")）"
    if [[ ! -f "$generator" || ! -x "$python_bin" ]]; then
        error "Caddyfile 生成入口不可用: $generator"
        return 1
    fi

    DMZ_DOMAIN="${DMZ_DOMAIN}" \
    DMZ_WEBUI_HOST="${DMZ_WEBUI_HOST:-127.0.0.1}" \
    DMZ_CADDY_PORT="${DMZ_CADDY_PORT:-8443}" \
    DMZ_CADDY_TLS_MODE="${DMZ_CADDY_TLS_MODE:-manual}" \
    DMZ_ACME_EMAIL="${ACME_EMAIL:-}" \
    DMZ_SECRET_KEY="${DMZ_SECRET_KEY:-deploy-caddy-generation-only}" \
        "$python_bin" "$generator"

    # 配置续期钩子（仅在非 443 模式且使用 LE 证书时）
    if [[ "$mode" == "non443" && "${USE_LE_CERT:-0}" == "1" ]]; then
        mkdir -p /etc/letsencrypt/renewal-hooks/deploy
        tee /etc/letsencrypt/renewal-hooks/deploy/restart-caddy.sh > /dev/null <<'HOOKEOF'
#!/bin/bash
chgrp -R caddy /etc/letsencrypt/live /etc/letsencrypt/archive
chmod 750 /etc/letsencrypt/live /etc/letsencrypt/archive
find /etc/letsencrypt/live -type f -exec chmod 640 {} \;
find /etc/letsencrypt/archive -type f -exec chmod 640 {} \;
systemctl restart caddy
HOOKEOF
        chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-caddy.sh
        info "certbot 续期钩子已配置"
    fi
}

# -------------- systemd 环境变量覆盖 --------------

install_service_override() {
    local dropin_dir="/etc/systemd/system/dmz-webui.service.d"
    mkdir -p "$dropin_dir"
    cat > "${dropin_dir}/override.conf" <<EOF
[Service]
Environment="DMZ_DOMAIN=${DMZ_DOMAIN}"
Environment="DMZ_WEBUI_HOST=${DMZ_WEBUI_HOST:-127.0.0.1}"
Environment="DMZ_CADDY_PORT=${DMZ_CADDY_PORT:-8443}"
Environment="DMZ_CADDY_TLS_MODE=${DMZ_CADDY_TLS_MODE:-manual}"
Environment="DMZ_ACME_EMAIL=${ACME_EMAIL:-}"
Environment="DMZ_ICP_NUMBER=${DMZ_ICP_NUMBER:-}"
Environment="DMZ_SITE_TITLE=${DMZ_SITE_TITLE:-DMZ WebUI}"
Environment="DMZ_TAB_TITLE=${DMZ_TAB_TITLE:-DMZ WebUI}"
EOF
    chmod 600 "${dropin_dir}/override.conf"
    info "systemd 环境变量覆盖已写入: ${dropin_dir}/override.conf"
}

# -------------- ufw 迁移 --------------

migrate_ufw() {
    if ! command -v ufw &>/dev/null; then
        info "未检测到 ufw，跳过迁移"
        return 0
    fi

    warn "检测到系统已安装 ufw，将自动迁移到 nftables..."
    mkdir -p /etc/dmz-webui
    local backup_file="/etc/dmz-webui/ufw-backup-${TIMESTAMP:-$(date +%Y%m%d-%H%M%S)}.txt"
    ufw status verbose numbered > "$backup_file" 2>/dev/null || true
    info "ufw 规则已备份: $backup_file"

    if ufw status 2>/dev/null | grep -q "Status: active"; then
        info "ufw 当前为活动状态，正在禁用..."
        ufw --force disable >> "$LOG_FILE" 2>&1 || warn "禁用 ufw 失败，请手动检查"
    fi

    if systemctl is-enabled ufw &>/dev/null; then
        run_cmd "禁用 ufw 开机自启" systemctl disable ufw --now
    fi

    info "ufw 已迁移并禁用，后续防火墙规则由 nftables 统一管理"
}
