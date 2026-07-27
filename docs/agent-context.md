# Agent Context

## 当前主任务

nftables 所有权收敛代码已完成，下一阶段是目标服务器部署联调与 Docker
连通性验收。

## 当前入口

- 实现：`backend/firewall.py`
- 后端调用：`backend/main.py`
- 部署入口：`scripts/apply_nftables.py`
- 当前进度：`docs/progress/PROGRESS-20260727-nftables-ownership-v1.md`
- 收口报告：`docs/reports/REPORT-20260727-nftables-ownership-v1.md`
- 已归档计划：
  `docs/archive/plans/PLAN-20260727-nftables-ownership-v1.md`

## 固定验收

- `python3 -m unittest discover -s backend/tests -v`
- `npm run build`（工作目录 `frontend`）
- 隔离或真实环境确认 `DOCKER`/外部哨兵链在应用项目规则后保持不变。

## 阻塞与风险

- 尚未执行真实服务器部署。
- 部署前必须备份 `/etc/nftables.conf`、完整 ruleset 和 `iptables-save`。
- 不得通过重启 nftables、全局 flush 或重启 Docker完成迁移。
