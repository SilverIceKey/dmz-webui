# DERP 共享 443 的 Caddy SNI 透传计划

> 归档状态：已完成本地实现与自动验证。替代入口：
> `docs/progress/PROGRESS-20260728-derp-sni-passthrough-v1.md` 和
> `docs/reports/REPORT-20260728-derp-sni-passthrough-v1.md`。
> 归档时间：2026-07-28。

## 状态

- 阶段：本地实现与自动验证完成，等待目标服务器部署联调。
- 目标：在不改变现有 WebUI、Headscale HTTP 路由的前提下，让
  `derper.silvericekey.top:443` 通过 Caddy 四层 SNI 分流透传到本机
  DERP `127.0.0.1:41103`。

## 背景与证据

- Headscale 当前在 `127.0.0.1:9091` 提供 HTTP 服务，可以继续使用现有
  Caddy HTTP `reverse_proxy`。
- DERP 在 TLS 内从 HTTP 切换为自定义双向二进制协议。Tailscale 官方明确
  要求不要把 DERP 放在普通 HTTP 代理后面。
- 当前项目生成的 Caddyfile 只有 HTTP 层 `reverse_proxy`，不能完成原始
  TCP/TLS 透传。
- Caddy 官方发行包不包含四层模块。`caddy-l4` 可以作为 Caddy HTTP
  listener wrapper，在 HTTP TLS 处理之前按 ClientHello SNI 匹配并原样
  代理 TCP 流量，其余连接继续交给现有 Caddy HTTP/TLS 链路。
- `caddy-l4` 使用 Apache-2.0 许可证，但属于第三方、仍声明为开发中的模块；
  引入后 Caddy 将从发行版标准二进制变为自定义构建。

## 已确认配置事实

- DERP 对外域名必须统一为 `derper.silvericekey.top`；原 Compose 中的
  `home.silvericekey.fun` 与 DERP map 不一致。
- DERP 外部端口为 TCP 443，内部监听保留 TCP 41103。
- STUN 不经过 Caddy，继续直接开放 UDP 3478。
- `InsecureForTests` 只用于测试关闭 TLS 校验，生产 DERP map 必须删除该
  字段，并让 DERP 提供受客户端信任的证书。
- `ghcr.io/yangchuansheng/derper` 的 manual 模式从证书目录读取
  `<DERP_DOMAIN>.crt` 和 `<DERP_DOMAIN>.key`。本例必须存在：
  `/usr/local/project/cert/derper.silvericekey.top.crt` 和
  `/usr/local/project/cert/derper.silvericekey.top.key`。
- 证书目录只读挂载时，缺少上述文件会导致镜像无法自动生成证书，部署前必须
  显式检查。

## 目标拓扑

```text
TCP 443
  -> Caddy listener wrapper
     -> SNI=derper.silvericekey.top
        -> 原样 TLS/TCP 透传到 127.0.0.1:41103
           -> DERP 自己完成 TLS 和 DERP 协议处理
     -> 其他 SNI
        -> Caddy 原有 TLS/HTTP 处理
           -> WebUI、Headscale 9091、静态文件等现有站点路由

UDP 3478
  -> Docker 直接发布
     -> DERP STUN
```

不另建一个内部 HTTPS Caddy 监听端口。采用 listener wrapper 后，现有 HTTP
站点仍由同一个 Caddy HTTP server 监听 443，只有命中 DERP SNI 的 TCP
连接会提前被四层模块接管。

## 接口与数据契约

新增独立的“TCP/SNI 透传”资源，不把四层路由塞入现有带 `path` 的 HTTP
站点路由模型。

- 数据文件：`/etc/dmz-webui/sni_routes.json`
- API：
  - `GET /api/caddy/sni-routes`
  - `POST /api/caddy/sni-routes`
  - `PUT /api/caddy/sni-routes/{id}`
  - `DELETE /api/caddy/sni-routes/{id}`
- 字段：
  - `id: int`
  - `hostname: str`
  - `dest_host: str`
  - `dest_port: int`
  - `comment: str`
- 约束：
  - 只允许标准 443 模式。
  - hostname 必须属于 `DMZ_ROUTE_DOMAIN`。
  - hostname 在 SNI 路由中必须唯一。
  - hostname 不得同时存在于 HTTP 站点路由中，避免同一 SNI 的协议归属
    含糊。
  - 目标主机和端口沿用严格校验，不接受 Caddyfile 注入字符。
  - 保存前确认当前 Caddy 二进制包含所需 Layer 4 模块；缺失时返回明确错误，
    不写配置或 JSON。

前端在“SSL 代理”页新增独立的“TCP/SNI 透传”区域，表单只显示访问域名、
目标主机、目标端口和备注，并提示该类型不负责证书签发、不处理 UDP。

## Caddyfile 生成契约

存在 SNI 路由时，在全局块生成：

```caddyfile
{
    servers :443 {
        listener_wrappers {
            layer4 {
                @sni_route_1 tls sni derper.silvericekey.top
                route @sni_route_1 {
                    proxy tcp/127.0.0.1:41103
                }
            }
            tls
        }
    }
}
```

ACME 邮箱继续位于同一全局块；其余 HTTP 站点块保持现有生成行为。没有 SNI
路由时不生成 listener wrapper，保持历史配置。

所有 SNI CRUD 继续使用当前候选配置事务：先构建并执行 `caddy validate`，
再写 Caddyfile、graceful reload，最后提交 JSON；失败恢复旧 Caddyfile 和旧
JSON。

## Caddy 依赖与部署策略

- 已采用 `caddy-l4@v0.1.0`，许可证 Apache-2.0。
- 该插件的发布模块声明依赖 Caddy 2.11.1 和 Go 1.25；实际官方自定义构建
  解析为 Caddy 2.11.4，不能假定目标机发行版 Caddy 与其兼容。
- 实施中已于 2026-07-28 实测 Caddy 官方自定义下载接口：请求固定
  Caddy 2.11.1 时仍返回 Caddy 2.11.4；`caddy-l4` 能固定为 v0.1.0，
  `caddy.listeners.layer4`、`layer4.handlers.proxy` 和
  `layer4.matchers.tls` 均存在。
- 用户已确认固定安装 Caddy 2.11.4 + `caddy-l4` v0.1.0。这样可直接使用
  Caddy 官方构建接口，不在目标机引入 Go/xcaddy 或 Docker 构建链。
- 首次启用 SNI 功能前，部署/更新脚本会：
  1. 备份当前 Caddy 二进制并记录 `caddy version`、`caddy list-modules`。
  2. 安装经固定版本构建的自定义 Caddy，而不是每次部署追随 `latest`。
  3. 验证 Layer 4 listener wrapper、TLS matcher 和 proxy 模块存在。
  4. 用候选配置执行 `caddy validate`。
  5. 仅在全部检查通过后切换二进制并 reload/restart。
- 回滚时恢复原 Caddy 二进制和原 Caddyfile。
- 系统包升级不能静默覆盖自定义二进制；Debian/Ubuntu 按 Caddy 官方的
  `dpkg-divert` 与 `update-alternatives` 方式管理标准版和自定义版。

第三方模块方案和 Caddy 2.11.4 调整均已由用户确认。

## DERP Compose 目标配置

Compose 不属于本仓库。按用户要求，完整 Compose 不写入或提交 Git，仅在
最终交付消息中输出。仓库文档只保留协议边界、证书要求与验收方法。

## DERP map 目标配置

```json
{
  "Regions": {
    "901": {
      "RegionID": 901,
      "RegionCode": "SilverIceKey",
      "RegionName": "SilverIceKey Derper",
      "Nodes": [
        {
          "Name": "901a",
          "RegionID": 901,
          "DERPPort": 443,
          "STUNPort": 3478,
          "STUNOnly": false,
          "HostName": "derper.silvericekey.top"
        }
      ]
    }
  }
}
```

如服务器有固定公网 IPv4/IPv6，目标机联调时再由用户提供真实地址后写入
`IPv4`/`IPv6`；不得伪造地址。

## 实施步骤

1. 增加 SNI 路由模型、存储、冲突校验和 Caddyfile 生成函数。
2. 增加独立 CRUD，并接入现有 Caddy 候选配置事务。
3. 增加前端列表、表单、错误展示和能力提示。
4. 增加固定版本自定义 Caddy 的安装、模块检查、备份与回滚流程。
5. 增加证书文件名、DERP map 和部署顺序指南；Compose 仅在最终交付输出。
6. 补齐后端单元/事务测试、脚本回放和前端构建验证。
7. 在真实目标机完成 Caddy、DERP、STUN 和 Tailscale 客户端联调后新增部署
   报告；联调前不宣称功能已验收。

## 验收矩阵

- 无 SNI 路由：生成结果与现有 Caddyfile 行为一致。
- DERP SNI：`openssl s_client -servername derper.silvericekey.top` 返回
  DERP 持有的可信证书。
- 普通 HTTPS：WebUI、Headscale 9091 路由和静态文件不受影响。
- 协议验证：`tailscale netcheck` 能识别区域 901，真实节点能建立 DERP
  连接。
- STUN：使用 Tailscale `stunc` 或 `tailscale netcheck` 验证 UDP 3478。
- 隔离：公网无法直接连接 TCP 41103，宿主机回环可连接。
- 事务：无 Layer 4 模块、Caddy 校验失败、reload 失败、JSON 写入失败时均
  保持旧配置有效。
- 回滚：可恢复标准 Caddy 二进制与旧 Caddyfile。
- 自动检查：
  - `python3 -m unittest discover -s backend/tests -v`
  - `npm run build`
  - `python3 -m py_compile ...`
  - `bash -n scripts/common.sh scripts/deploy.sh scripts/update.sh`
  - `git diff --check`

## 明确不做

- 不把 DERP 当 HTTP/WebSocket 反代。
- 不由 Caddy 为透传后的 DERP 终止 TLS 或自动续签 DERP 证书。
- 不让 Caddy 处理 UDP 3478。
- 不编辑本仓库外的 Compose、证书或 Headscale 配置。
- 不在没有真实固定公网地址时填写 DERP map 的 IPv4/IPv6。
- 不顺带修改 Headscale 9091 的既有 HTTP 路由链路。

## 风险与回滚

- `caddy-l4` 为第三方且仍在开发，升级可能破坏 Caddyfile 语法；因此固定
  版本并在升级前验证。
- DERP 证书不是由 Caddy管理；manual 证书更新后必须重启 DERP，需由现有
  证书续期流程负责。
- SNI 分流依赖客户端发送正确 SNI；DERP map 的 HostName 与证书域名必须
  始终一致。
- 若自定义 Caddy 安装或目标机联调失败，恢复标准 Caddy 二进制、移除 SNI
  数据文件并恢复旧 Caddyfile，现有 HTTP 路由继续工作。
