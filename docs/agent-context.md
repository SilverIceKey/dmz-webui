# Agent Context

## 当前主任务

当前主任务是让 `derper.silvericekey.top:443` 与现有 Caddy HTTPS 站点共享
443：按 TLS SNI 将 DERP 原始 TCP 流量透传到 `127.0.0.1:41103`，Headscale
`127.0.0.1:9091` 仍使用现有 HTTP 反代。代码、文档和本地自动验证已完成，
等待目标服务器部署联调。

## 当前入口

- Caddy 路由实现：`backend/caddy_routes.py`
- 后端/API 入口：`backend/main.py`
- 部署生成入口：`scripts/generate_caddyfile.py`
- 已归档计划：
  `docs/archive/plans/PLAN-20260728-derp-sni-passthrough-v1.md`
- 当前进度：`docs/progress/PROGRESS-20260728-derp-sni-passthrough-v1.md`
- 当前报告：`docs/reports/REPORT-20260728-derp-sni-passthrough-v1.md`
- 当前指南：`docs/guides/GUIDE-20260728-tcp-sni-passthrough-v1.md`
- 当前进度：`docs/progress/PROGRESS-20260728-caddy-site-routes-v1.md`
- 收口报告：`docs/reports/REPORT-20260728-caddy-site-routes-v1.md`
- 收口报告：`docs/reports/REPORT-20260727-nftables-ownership-v1.md`
- 保存/删除误报报告：
  `docs/reports/REPORT-20260727-rule-mutation-response-v1.md`
- 链闭合括号换行报告：
  `docs/reports/REPORT-20260727-nft-chain-newline-v1.md`
- 本机端口开放报告：
  `docs/reports/REPORT-20260727-local-port-open-v1.md`
- 已归档当前计划：
  `docs/archive/plans/PLAN-20260728-caddy-path-routes-v1.md`
- 已归档标题计划：
  `docs/archive/plans/PLAN-20260728-dynamic-site-title-v1.md`
- 标题功能进度：
  `docs/progress/PROGRESS-20260728-dynamic-site-title-v1.md`
- 标题功能报告：
  `docs/reports/REPORT-20260728-dynamic-site-title-v1.md`
- 已归档修复计划：
  `docs/archive/plans/PLAN-20260728-update-config-groups-v1.md`
- 配置分组进度：
  `docs/progress/PROGRESS-20260728-update-config-groups-v1.md`
- 配置分组报告：
  `docs/reports/REPORT-20260728-update-config-groups-v1.md`
- 已归档基础域名修复计划：
  `docs/archive/plans/PLAN-20260728-route-base-domain-v1.md`
- 基础域名修复进度：
  `docs/progress/PROGRESS-20260728-route-base-domain-v1.md`
- 基础域名修复报告：
  `docs/reports/REPORT-20260728-route-base-domain-v1.md`
- 登录页备案号进度：
  `docs/progress/PROGRESS-20260727-login-icp-footer-v1.md`
- 动态备案号配置入口：`scripts/common.sh`、`GET /api/public-config`
- 已归档计划：
  `docs/archive/plans/PLAN-20260727-nftables-ownership-v1.md`

## 固定验收

- `python3 -m unittest discover -s backend/tests -v`（当前 71 项）
- `npm run build`（工作目录 `frontend`）
- 固定自定义 Caddy 验证完整生成配置，并用高位端口检查 DERP SNI 证书与
  普通 HTTPS 响应共存。
- 目标服务器执行 `caddy validate --config /etc/caddy/Caddyfile
  --adapter caddyfile`，并检查 Caddy journal 中的 ACME 签发结果。
- 端口转发生成配置执行 `nft -c -f -`。
- 隔离或真实环境确认 `DOCKER`/外部哨兵链在应用项目规则后保持不变。

## 阻塞与风险

- 尚未执行真实服务器部署。
- 尚未取得原失败请求的 journal/HTTP 状态，部署后必须复验保存与删除响应。
- 目标机现有的 `# 注释}` 畸形配置需通过一次新增、编辑或部署同步触发自动
  规范化，并复核 `/etc/nftables.conf`。
- 本机开放要求业务服务监听 `0.0.0.0` 或实际网卡；仅监听 `127.0.0.1`
  应继续通过 Caddy/SSL 代理暴露。
- 二级域名自动证书要求标准 443 模式、DNS 指向本机且公网 80/443 可达。
- 已下载固定自定义 Caddy 候选并完成真实配置校验，但未安装为本机系统服务；
  ACME 和 systemd/alternatives 仍必须在目标机验证。
- 动态标题尚未在目标机执行 `update.sh` 交互与浏览器人工验收。
- 从旧版脚本自更新后需重新运行最新版 `update.sh`，才能看到新的分组提示。
- 当前代码已支持 TCP/SNI 透传，但 DERP STUN UDP 仍不经过 Caddy。
- 标准 443 部署会切换到 Caddy 2.11.4 + `caddy-l4` 0.1.0 自定义二进制；
  目标机下载、alternatives 和回滚尚未实机验证。
- DERP 必须自行终止 TLS；证书需命名为
  `derper.silvericekey.top.crt/.key`，Caddy 不为透传流量签发证书。
- `InsecureForTests` 只用于测试，生产 DERP map 不应设置。
- 部署前必须备份 `/etc/nftables.conf`、完整 ruleset 和 `iptables-save`。
- 不得通过重启 nftables、全局 flush 或重启 Docker完成迁移。
