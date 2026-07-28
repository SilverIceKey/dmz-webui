# TCP/SNI 透传使用与验收指南

## 适用范围

TCP/SNI 透传用于 TLS 内不是普通 HTTP 的服务，例如 Tailscale DERP。普通
Headscale HTTP、WebSocket、静态文件仍使用“域名与路径路由”，不要改成 SNI
透传。

本功能只处理 TCP 443。UDP 服务（例如 DERP STUN 3478）必须由服务自身、
Docker 端口发布和防火墙单独开放。

## 工作方式

标准 443 模式下，Caddy listener wrapper 先读取 TLS ClientHello：

- SNI 命中透传规则时，TLS 字节原样转发到目标主机和端口。
- 未命中时，连接继续进入现有 Caddy TLS/HTTP 链路。

Caddy 不会为透传目标终止 TLS、申请证书或注入 HTTP 请求头。目标服务必须
自行提供与 SNI 域名匹配、客户端信任的证书。

## 部署依赖

`deploy.sh` 和 `update.sh` 在标准 443 模式下安装并核验：

- Caddy 2.11.4
- `caddy-l4` 0.1.0
- `caddy.listeners.layer4`
- `layer4.handlers.proxy`
- `layer4.matchers.tls`

安装使用 Caddy 官方自定义构建接口，并按 Caddy 官方 Debian/Ubuntu 方案通过
`dpkg-divert` 和 `update-alternatives` 保留系统版与自定义版。候选二进制会
先核验核心版本、插件版本、模块和现有 Caddyfile；失败时不切换。更新或重启
失败时恢复旧 Caddyfile 和旧 Caddy 二进制。

下载接口未来若不再返回已验证的 Caddy 2.11.4，脚本会拒绝安装，不会静默
升级。升级固定版本前必须重新验证插件兼容性并更新计划。

## 页面配置

进入“SSL 代理”页面的“TCP/SNI 透传”区域：

1. 访问域名填写客户端实际使用的 TLS SNI，例如
   `derper.example.com`。
2. 目标主机填写宿主机可访问的目标地址，例如 `127.0.0.1`。
3. 目标端口填写目标 TLS 服务监听端口，例如 `41103`。
4. 保存后检查页面显示 `域名:443 -> 目标主机:目标端口`。

约束：

- 仅标准 443 模式可保存。
- 域名必须属于部署时配置的 `DMZ_ROUTE_DOMAIN`。
- WebUI 主域名不能被 SNI 规则接管。
- 同一域名只能有一条 SNI 规则。
- SNI 域名不能同时用于 HTTP 站点路由。
- 切换到非 443 模式前必须先删除全部 SNI 透传规则，否则配置生成会拒绝
  切换并保留旧 Caddy 配置。

## DERP 特别要求

- DERP map 的 `HostName` 必须与 SNI 域名、DERP `--hostname` 和证书域名
  完全一致。
- DERP 内部 TLS 监听只应暴露给本机 Caddy；例如 Docker 发布到
  `127.0.0.1:41103`，不要同时公开 TCP 41103。
- DERP 证书目录必须包含 `<hostname>.crt` 和 `<hostname>.key`。
- manual 证书更新后需要重启 DERP。
- 生产 DERP map 不得设置 `InsecureForTests`。
- STUN UDP 3478 不经过 Caddy，也不应限速。

按用户要求，具体 Docker Compose 不保存在仓库中，由交付时单独提供。

## 验收

### 静态检查

```bash
caddy version
caddy build-info | grep github.com/mholt/caddy-l4
caddy list-modules | grep -E \
  'caddy.listeners.layer4|layer4.handlers.proxy|layer4.matchers.tls'
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

### 监听隔离

```bash
ss -lntup | grep -E ':(443|41103|3478)\b'
```

预期：

- Caddy 监听公网 TCP 443。
- DERP TCP 41103 仅绑定 `127.0.0.1`。
- DERP STUN 监听公网 UDP 3478。

### TLS 与普通 HTTPS

```bash
openssl s_client \
  -connect <服务器公网地址>:443 \
  -servername derper.example.com \
  -verify_hostname derper.example.com </dev/null

curl -fsS https://<WebUI 域名>/admin >/dev/null
curl -fsS https://<Headscale 域名>/health
```

第一条应返回 DERP 自己持有的可信证书；WebUI 与 Headscale 应继续正常访问。

### Tailscale/DERP

在真实客户端执行：

```bash
tailscale netcheck
```

检查自定义 DERP 区域可达、UDP/STUN 状态和首选区域。最终验收还应使用两个
真实节点确认在无法直连时能建立 DERP 中继，并检查 DERP 与 Caddy journal。

## 回滚

部署/更新过程会自动回滚。需要人工切回系统 Caddy 时：

```bash
sudo update-alternatives --set caddy /usr/bin/caddy.default
sudo systemctl restart caddy
```

切换前必须先移除全部 SNI 透传规则并生成不含 `listener_wrappers` 的
Caddyfile，否则标准 Caddy 无法加载配置。
