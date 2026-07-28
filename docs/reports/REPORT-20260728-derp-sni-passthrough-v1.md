# DERP 共享 443 的 TCP/SNI 透传实现报告

## 背景

Headscale 在 `127.0.0.1:9091` 提供普通 HTTP 服务，现有 Caddy
`reverse_proxy` 可以处理。DERP 则在 TLS 内从 HTTP 切换到自定义双向二进制
协议，不能放在普通 HTTP 代理后面。目标是让
`derper.silvericekey.top:443` 与现有 WebUI、Headscale 和静态站点共享
公网 TCP 443。

## 根因与证据

原系统只有 HTTP 层 Caddy 路由，Caddy 标准发行版也没有原始 TCP/SNI
matcher 和 proxy handler，因此无论新增路径还是普通子域名 HTTP 反代，都
不能正确转发 DERP。

采用 `caddy-l4` listener wrapper 后，可以在 Caddy HTTP TLS 处理之前读取
ClientHello SNI。命中 DERP 域名时原样透传 TLS/TCP；未命中时继续执行
Caddy 原有 TLS/HTTP 链路。真实自定义 Caddy 配置验证和高位端口端到端测试
均证实该调用链。

## 实现范围

- 新增独立 `/api/caddy/sni-routes` CRUD。
- 新增 `/etc/dmz-webui/sni_routes.json` 原子存储。
- 新增 SNI 域名、目标和标准 443 模式校验。
- 禁止 SNI 域名与 WebUI 主域名、HTTP 站点路由或其他 SNI 规则冲突。
- Caddyfile 全局块按规则生成 `servers :443` listener wrapper。
- 保存前检查 Layer 4 listener、TLS matcher 和 TCP proxy 模块。
- Caddy validate、写入、reload、JSON 提交使用候选配置事务，失败回滚。
- “SSL 代理”页面增加独立 TCP/SNI 列表、添加、编辑和删除。
- 标准 443 部署固定使用 Caddy 2.11.4 与 `caddy-l4` 0.1.0。
- 部署/更新脚本核验候选版本、模块和当前 Caddyfile，通过
  `dpkg-divert`/`update-alternatives` 切换；失败恢复二进制和 Caddyfile。
- 增加使用、证书、隔离、回滚和目标机验收指南。

按用户要求，具体 DERP Docker Compose 未写入仓库，只在最终交付中输出。

## 验证步骤与证据

已执行：

1. `python3 -m unittest discover -s backend/tests -v`
   - 71 项通过。
   - 覆盖模型边界、域名冲突、非 443 模式、Caddy 生成、模块缺失 503、
     reload 失败、JSON 失败和删除最后规则时的降级路径。
2. `npm run build`（`frontend`）
   - TypeScript 与 Vite 生产构建通过，894 个模块完成转换。
3. `python3 -m py_compile backend/main.py backend/caddy_routes.py
   scripts/generate_caddyfile.py`
   - 通过。
4. `bash -n scripts/common.sh scripts/deploy.sh scripts/update.sh`
   - 通过。
5. `git diff --check`
   - 通过。
6. 固定自定义 Caddy 二进制检查：
   - `caddy version` 返回 2.11.4。
   - `build-info` 返回 `github.com/mholt/caddy-l4 v0.1.0`。
   - 三个必要模块均存在。
7. 使用真实自定义 Caddy 验证包含
   `derper.silvericekey.top -> 127.0.0.1:41103` 与 Headscale HTTP 路由的
   完整生成配置：
   - `caddy validate` 返回 `Valid configuration`。
8. 本机高位端口端到端验证：
   - DERP SNI 连接拿到测试上游的 `CN = derper.example.com` 证书。
   - 普通 HTTPS SNI 由同一 Caddy 返回 `web-ok`。

未执行：

- 目标服务器真实 `update.sh` 和 systemd/alternatives 切换。
- 公网 `derper.silvericekey.top:443` 访问。
- 用户真实 DERP 证书、容器和 UDP 3478。
- `tailscale netcheck`、`derpprobe` 和两个真实节点的 DERP 中继。

## 结论

代码层已经实现 DERP 与普通 HTTPS 共用 TCP 443 的 SNI 透传能力，并保持
Headscale 9091 的原 HTTP 链路不变。候选配置、运行态 Caddy 和 JSON 均有
失败回滚，不会把 DERP 当作普通 HTTP 代理。

## 剩余风险

- `caddy-l4` 是第三方且仍处于开发状态；版本升级必须重新验证配置语法和
  listener 行为。
- Caddy 官方构建接口未来若返回其他核心版本，脚本会拒绝静默升级，需要先
  修改固定版本并重新验收。
- DERP TLS 由容器自行终止；证书申请、续期和更新后重启不属于 Caddy 管理。
- SNI 依赖 DERP map、DNS、证书和 DERP hostname 完全一致。
- UDP 3478 不经过 Caddy，仍受云防火墙、宿主机防火墙和 Docker 发布影响。

## 后续动作

- 在目标服务器运行最新版更新脚本并保存 Caddy、dmz-webui journal。
- 核验 DERP 证书文件名、证书链、有效期和续期重启流程。
- 创建真实 SNI 规则，验证 WebUI、Headscale 和 DERP 三条链路。
- 完成真实 Tailscale/DERP/STUN 验收后新增部署联调报告。
