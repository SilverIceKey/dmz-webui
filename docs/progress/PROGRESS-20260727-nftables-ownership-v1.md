# nftables 所有权收敛进度

## 当前状态

- 状态：保存/删除误报的事务修复与本地隔离验证完成，等待部署复验。
- 当前结论：全局 `flush ruleset` 根因已消除，运行时只替换两个项目独占表。

## 最近关键结论

- 防火墙、SSL、CN IP 和控制台入口均已接入统一定向应用。
- 部署与更新不再重启 nftables。
- 旧版迁移不会扫描或复制 Docker 链中的 DNAT。
- 11 项单测、前端构建及隔离 nftables 迁移验证通过。
- 已确认 SSL CRUD 存在先写 JSON、后应用运行态的非事务顺序。
- 已确认 Caddy reload 失败会在当前 API 请求内 fallback restart。
- SSL/Caddy/nftables 已改为失败回滚、成功后提交 JSON。
- 普通 NAT 变更只替换 NAT 表，隔离验证确认 filter/input 哨兵保持不变。
- 当前回归测试为 20 项，前端生产构建通过。

## 下一步

- 在目标服务器部署后采集 dmz-webui、Caddy journal 与浏览器 Network 证据。
- 复验防火墙与 SSL 页面的新增、修改、删除成功提示及实际运行态。

## 阻塞项

- 当前工作区不是实际部署服务器，无法验证真实 Docker 容器连通性。

## 未证实风险

- 目标机 nftables、iptables 后端和 Docker 版本组合尚未实机验证。
- 旧项目链中的非标准手工 input/forward 规则是否存在尚未确认。
