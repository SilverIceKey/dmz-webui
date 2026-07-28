# Agent Context

## 当前主任务

当前主任务是增加 Caddy 域名与路径路由，支持二级域名反向代理及主域名/
子域名静态文件访问；代码与本地自动验证已完成，等待目标服务器部署联调。

## 当前入口

- Caddy 路由实现：`backend/caddy_routes.py`
- 后端/API 入口：`backend/main.py`
- 部署生成入口：`scripts/generate_caddyfile.py`
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
- 登录页备案号进度：
  `docs/progress/PROGRESS-20260727-login-icp-footer-v1.md`
- 动态备案号配置入口：`scripts/common.sh`、`GET /api/public-config`
- 已归档计划：
  `docs/archive/plans/PLAN-20260727-nftables-ownership-v1.md`

## 固定验收

- `python3 -m unittest discover -s backend/tests -v`（当前 48 项）
- `npm run build`（工作目录 `frontend`）
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
- 当前开发环境未安装 Caddy，真实配置校验和 ACME 签发必须在目标机完成。
- 部署前必须备份 `/etc/nftables.conf`、完整 ruleset 和 `iptables-save`。
- 不得通过重启 nftables、全局 flush 或重启 Docker完成迁移。
