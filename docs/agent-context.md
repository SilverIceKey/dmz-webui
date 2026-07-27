# Agent Context

## 当前主任务

nftables 所有权收敛及保存/删除误报事务修复已完成，下一阶段是目标服务器部署
联调、成功响应与 Docker 连通性验收。

## 当前入口

- 实现：`backend/firewall.py`
- 后端调用：`backend/main.py`
- 部署入口：`scripts/apply_nftables.py`
- 当前进度：`docs/progress/PROGRESS-20260727-nftables-ownership-v1.md`
- 收口报告：`docs/reports/REPORT-20260727-nftables-ownership-v1.md`
- 保存/删除误报报告：
  `docs/reports/REPORT-20260727-rule-mutation-response-v1.md`
- 已归档计划：
  `docs/archive/plans/PLAN-20260727-nftables-ownership-v1.md`

## 固定验收

- `python3 -m unittest discover -s backend/tests -v`（当前 20 项）
- `npm run build`（工作目录 `frontend`）
- 隔离或真实环境确认 `DOCKER`/外部哨兵链在应用项目规则后保持不变。

## 阻塞与风险

- 尚未执行真实服务器部署。
- 尚未取得原失败请求的 journal/HTTP 状态，部署后必须复验保存与删除响应。
- 部署前必须备份 `/etc/nftables.conf`、完整 ruleset 和 `iptables-save`。
- 不得通过重启 nftables、全局 flush 或重启 Docker完成迁移。
