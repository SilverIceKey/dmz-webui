# DMZ WebUI

DMZ 网络管控 Web 管理界面。基于 React + TypeScript 前端、Python FastAPI 后端，使用 Linux PAM 系统账户认证。

## 功能

- **防火墙规则管理**：分别管理 nftables 端口转发和本机端口开放规则
- **站点路由管理**：按主域名/子域名和路径管理 Caddy 反向代理及静态文件
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
│   ├── caddy_routes.py      # 站点路由冲突检查与 Caddy 片段生成
│   ├── firewall.py          # 项目独占 nftables 表的校验与定向应用
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
│   ├── apply_nftables.py    # 仅应用本项目拥有的 nftables 表
│   └── update.sh            # 增量更新脚本（含自动回滚）
└── README.md
```

## 首次部署

将项目复制到目标服务器，然后执行：

```bash
cd /path/to/dmz-webui
sudo ./scripts/deploy.sh
```

`deploy.sh` 会先交互式询问域名、Caddy 模式（标准 443 / 非 443 端口
8443）、可选 ICP 备案号等配置，然后自动完成：
1. 检查并安装系统依赖（python3, npm, nftables, caddy, libpam0g-dev）
2. 备份旧版本（如存在）
3. 复制项目到 `/opt/dmz-webui`
4. 创建 Python 虚拟环境并安装依赖
5. 构建前端并复制到 `backend/static`
6. 检查后端语法
7. 注册 systemd 服务并启动
8. 健康检查（访问 `http://127.0.0.1:5000/api/status`）
9. 同步 nftables 配置：迁移现有项目规则后，只定向应用
   `inet dmz_webui_filter` 和 `ip dmz_webui_nat` 两个项目独占表，并启用
   nftables 开机自启

部署和页面操作不会执行 `flush ruleset`，也不会重启整个 nftables 服务。
Docker、iptables-nft 及其他程序管理的表和链不属于 DMZ WebUI 的修改范围。

> 如果系统已安装 `ufw`，脚本会自动备份并禁用 `ufw`，后续防火墙统一由 nftables 管理。
> 你也可以提前设置环境变量 `DMZ_DOMAIN`、`DMZ_ROUTE_DOMAIN`、
> `DMZ_WEBUI_HOST`、
> `DMZ_SITE_TITLE`、`DMZ_TAB_TITLE`、`DMZ_ICP_NUMBER`、`CF_API_KEY`、
> `CF_EMAIL`，脚本会将其作为默认值。
> `DMZ_ICP_NUMBER` 留空时登录页不显示备案链接；配置会保存在
> `/etc/dmz-webui/install.conf` 并由后续更新复用。

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
6. **nftables 同步**：确保项目独占表与配置同步，不重启全局 nftables 服务
7. **健康检查**：多次重试验证 API 和页面可访问
8. **失败回滚**：任何步骤失败自动恢复旧版本并重启服务

**日志位置：** `/var/log/dmz-webui/update-<timestamp>.log`

更新脚本检测到已有部署配置时，会分别确认是否修改：

1. 公网与 Caddy 配置
2. 页面标题配置
3. 备案配置

三个分组互不影响；跳过公网与 Caddy 配置后仍会继续询问标题和备案。选择
修改页面标题后，可以交互式修改“站点标题”和“浏览器页签标题”：

- 站点标题显示在登录页和登录后导航栏左侧。
- 页签标题显示在浏览器标签页。
- 直接回车保留当前值，输入 `-` 恢复默认值 `DMZ WebUI`。
- 标题配置保存在 `/etc/dmz-webui/install.conf`，并通过 systemd 环境变量
  提供给后端；旧配置缺少字段时自动使用默认值。

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

## 防火墙规则类型

- **端口转发**：在 NAT prerouting 链执行 DNAT，将外部端口转发到目标
  IP 和端口。
- **本机端口开放**：在 filter input 链放行宿主机端口，适用于监听在
  `0.0.0.0` 或服务器实际网卡地址上的服务。

两种规则都支持全部、大陆 IP、境外 IP 和自定义 IP/CIDR 白名单。大陆 IP
集合分别存在于项目的 filter 与 NAT 表中，更新大陆 IP 时会同步更新两份
集合。

本机端口开放不会启动服务，也不会改变服务监听地址。仅监听
`127.0.0.1` 的服务仍不能通过公网地址直接访问；这类服务应通过 Caddy/SSL
代理暴露，或调整服务自身的监听地址。

## 域名与路径路由

“SSL 代理”页面的“域名与路径路由”支持：

- 反向代理，例如将 `https://headscale.example.com/` 转发到
  `127.0.0.1:9091`。
- 非根路径反向代理，并可选择转发前是否去掉路径前缀。
- 主域名或子域名静态文件，例如提供
  `https://static.example.com/derper.json`。

`DMZ_DOMAIN` 表示 WebUI 主站地址，`DMZ_ROUTE_DOMAIN` 表示允许创建站点
路由的基础域名。例如：

```text
DMZ_DOMAIN=www.example.com
DMZ_ROUTE_DOMAIN=example.com
```

此时允许 `example.com` 及其子域名，包括 `www.example.com` 和
`headscale.example.com`。历史配置没有 `DMZ_ROUTE_DOMAIN` 时，如果主站以
`www.` 开头会默认去掉该前缀，否则沿用主站域名。

主站的 `/`、`/admin` 和 `/assets` 保留给 WebUI；同一域名下不允许路径重复
或父子路径重叠。

二级域名启用 SSL 时，程序生成 Caddy 自动 HTTPS 站点配置。Caddy 会自动
申请并续签证书，无需为每个二级域名单独运行 certbot。使用前必须满足：

1. 部署使用标准 443 模式。
2. 二级域名的 A/AAAA 记录已解析到本机。
3. 公网 80 和 443 端口能到达 Caddy。

如果关闭 SSL，则该二级域名生成普通 `http://` 站点。同一个二级域名下的
所有路径必须使用相同的 SSL 设置。

静态规则保存后会显示专属目录：

```text
/var/lib/dmz-webui/caddy-static/<规则 ID>/
```

例如规则路径为 `/derper.json`，应将文件放到该目录下的
`derper.json`。配置子域名根路径 `/` 时，可按相对 URL 访问目录中的文件，
但不提供目录列表。文件和子目录需允许 `caddy` 服务用户读取。删除规则只
撤销访问路由，不删除已有文件。

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
- **nftables 所有权**：运行时仅替换 `inet dmz_webui_filter` 和
  `ip dmz_webui_nat`；禁止通过本项目清空全局 ruleset 或重载其他程序的规则
- **IP 转发持久化**：通过 `/etc/sysctl.d/99-dmz-webui-forwarding.conf` 持久化 `ip_forward`，并在 `dmz-webui.service` 的 `ExecStartPre` 中做运行时兜底
