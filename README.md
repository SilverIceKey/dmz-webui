# DMZ WebUI

DMZ 网络管控 Web 管理界面。基于 React + TypeScript 前端、Python FastAPI 后端，使用 Linux PAM 系统账户认证。

## 功能

- **防火墙 NAT 规则管理**：增删改查 nftables 端口映射规则
- **反向代理管理**：增删改查 Caddy 路径级反向代理
- **端口进程查看**：实时查看系统监听端口与占用进程
- **服务状态监控**：nftables / caddy 运行状态与一键重载
- **Linux 系统账户登录**：通过 PAM 使用系统用户认证

## 技术栈

- 前端：React 18 + TypeScript + Vite
- 后端：Python 3 + FastAPI + PAM + PyJWT
- 部署：systemd service + 自动 nftables 放行

## 项目结构

```
dmz-webui/
├── backend/
│   ├── main.py              # FastAPI 主程序
│   ├── requirements.txt     # Python 依赖
│   └── static/              # 前端构建产物（部署时生成）
├── frontend/
│   ├── src/
│   │   ├── main.tsx         # 前端入口
│   │   ├── App.tsx          # 路由配置
│   │   ├── utils/api.ts     # API 封装
│   │   ├── types/index.ts   # 类型定义
│   │   └── pages/           # 页面组件
│   ├── package.json
│   ├── vite.config.ts
│   └── index.html
├── systemd/
│   └── dmz-webui.service    # systemd 服务文件
├── scripts/
│   ├── deploy.sh            # 首次部署脚本
│   └── update.sh            # 增量更新脚本（含自动回滚）
└── README.md
```

## 首次部署

将项目复制到目标服务器，然后执行：

```bash
cd /path/to/dmz-webui
sudo ./scripts/deploy.sh
```

`deploy.sh` 会先交互式询问域名、Caddy 模式（标准 443 / 非 443 端口 8443）等配置，然后自动完成：
1. 检查并安装系统依赖（python3, npm, nftables, caddy, libpam0g-dev）
2. 备份旧版本（如存在）
3. 复制项目到 `/opt/dmz-webui`
4. 创建 Python 虚拟环境并安装依赖
5. 构建前端并复制到 `backend/static`
6. 检查后端语法
7. 注册 systemd 服务并启动
8. 健康检查（访问 `http://127.0.0.1:5000/api/status`）
9. 同步 nftables 配置：以项目 `configs/nftables.conf` 为基准，保留用户自定义规则与 SSL 代理规则，并启用 nftables 开机自启

> 如果系统已安装 `ufw`，脚本会自动备份并禁用 `ufw`，后续防火墙统一由 nftables 管理。
> 你也可以提前设置环境变量 `DMZ_DOMAIN`、`DMZ_WEBUI_HOST`、`CF_API_KEY`、`CF_EMAIL`，脚本会将其作为默认值。

**日志位置：** `/var/log/dmz-webui/deploy-<timestamp>.log`

## 更新

当代码有变更后，在目标服务器上执行：

```bash
cd /path/to/dmz-webui
sudo ./scripts/update.sh
```

`update.sh` 会自动完成：
1. **创建回滚备份**：完整备份当前运行版本到 `/opt/dmz-webui.rollback.<timestamp>`
2. **代码同步**：保留 `venv` 和日志，原子替换代码
3. **依赖更新**：Python 增量更新，前端按需 `npm install`
4. **重新构建**：前端重新编译
5. **平滑重启**：重启 systemd 服务并等待就绪
6. **nftables 同步**：确保 nftables 配置与项目基准同步并重启服务
7. **健康检查**：多次重试验证 API 和页面可访问
8. **失败回滚**：任何步骤失败自动恢复旧版本并重启服务

**日志位置：** `/var/log/dmz-webui/update-<timestamp>.log`

### 手动回滚

如果更新后发现问题，可手动回滚：

```bash
# 查看最新回滚备份
ls -1dt /opt/dmz-webui.rollback.* | head -1

# 手动回滚（示例）
sudo systemctl stop dmz-webui
sudo rm -rf /opt/dmz-webui
sudo cp -a /opt/dmz-webui.rollback.20240518-120000 /opt/dmz-webui
sudo systemctl start dmz-webui
```

## 访问

部署完成后访问：

- 标准 443 模式：`https://<DMZ_DOMAIN>/admin`
- 非 443 模式（8443）：`https://<DMZ_DOMAIN>:8443/admin`

使用目标服务器的 **Linux 系统账户** 登录。

## 管理命令

```bash
# 查看服务状态
systemctl status dmz-webui

# 重启服务
systemctl restart dmz-webui

# 查看实时日志
journalctl -u dmz-webui -f

# 查看部署/更新日志
tail -f /var/log/dmz-webui/deploy-*.log
tail -f /var/log/dmz-webui/update-*.log

# 清理旧备份（保留最近5个自动清理）
ls -1dt /opt/dmz-webui.backup.* | tail -n +6 | xargs rm -rf
ls -1dt /opt/dmz-webui.rollback.* | tail -n +6 | xargs rm -rf
```

## 注意事项

- 后端以 root 运行，因为需要读写 `/etc/nftables.conf` 和 `/etc/caddy/Caddyfile`
- 生产环境请修改 `DMZ_SECRET_KEY` 环境变量（编辑 `/etc/systemd/system/dmz-webui.service`）
- 确保 nftables 和 caddy 服务已安装
- `update.sh` 会保留虚拟环境和日志，更新时不会重复下载全部依赖
- 回滚备份最多保留 5 个，旧的会自动清理
- **nftables 持久化**：`dmz-webui.service` 已依赖 `nftables.service`，确保系统重启时 nftables 先于 WebUI 加载 `/etc/nftables.conf`
- **IP 转发持久化**：通过 `/etc/sysctl.d/99-dmz-webui-forwarding.conf` 持久化 `ip_forward`，并在 `dmz-webui.service` 的 `ExecStartPre` 中做运行时兜底
