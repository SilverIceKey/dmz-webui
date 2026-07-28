# DERP SNI 透传进度

## 当前状态

- 状态：代码、文档与本地自动验证完成，等待目标服务器部署联调。
- 当前结论：Headscale 9091 可继续走 HTTP 反代，DERP 必须使用四层 TCP/SNI
  透传，不能复用现有 HTTP `reverse_proxy`。

## 最近关键结论

- 推荐使用 Caddy HTTP listener wrapper 形式的 `caddy-l4`，仅提前接管
  `derper.silvericekey.top`，其余 443 流量继续进入现有 Caddy HTTP/TLS
  链路。
- 已按用户确认引入 Apache-2.0 的第三方实验性模块，固定为 Caddy 2.11.4
  与 `caddy-l4` 0.1.0。
- SNI 路由使用独立 API、JSON 和前端区域，保存时先验证模块和候选 Caddyfile，
  reload 成功后才提交 JSON，失败恢复旧状态。
- 部署/更新使用 `dpkg-divert`、`update-alternatives` 和候选二进制验证，
  Caddy 失败时恢复旧二进制与旧 Caddyfile。
- DERP Compose 应将 TCP 41103 绑定到 `127.0.0.1`，UDP 3478 继续公网
  发布。
- DERP 域名、证书文件名和 DERP map 统一为
  `derper.silvericekey.top`。
- 生产 DERP map 删除 `InsecureForTests`。
- Caddy 官方自定义构建接口实测返回 Caddy 2.11.4，不能按接口参数固定为
  原计划的 2.11.1；插件 v0.1.0 和所需模块均已核验。
- 后端 71 项测试、前端生产构建、Shell/Python 语法和差异检查通过。
- 固定版本真实 Caddy 已验证生成配置，并在高位端口完成 SNI 透传与普通
  HTTPS 共存测试。

## 下一步

- 在目标服务器运行最新版 `update.sh`，确认自定义 Caddy 安装、服务重启和
  alternatives 状态。
- 部署 DERP 后从页面创建
  `derper.silvericekey.top -> 127.0.0.1:41103`。
- 使用真实证书、`tailscale netcheck` 和两个真实节点完成 DERP/STUN 联调。

## 阻塞项

- 尚未执行目标服务器部署。
- 尚未取得 DERP 证书续期方式和目标机实际证书文件。

## 未证实风险

- 目标机能否下载并切换固定版本自定义 Caddy 尚未验证。
- `/usr/local/project/cert` 中是否已有正确命名、完整链且未过期的 DERP
  证书尚未验证。
- DERP 镜像固定 tag 在目标平台的架构支持尚未实机验证。
