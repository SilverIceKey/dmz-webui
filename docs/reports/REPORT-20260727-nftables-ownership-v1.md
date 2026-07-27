# nftables 所有权收敛与 Docker 规则保护报告

## 背景

端口转发、SSL 代理和控制台 nftables 重载都会执行
`nft -f /etc/nftables.conf`。旧配置包含 `flush ruleset`，会清空整机
nftables ruleset；在 iptables-nft 或 Docker nftables 场景下，Docker 链也会
被删除。

## 范围

- 收敛 DMZ WebUI 的 nftables 所有权。
- 修复防火墙 CRUD、CN IP 更新、SSL 代理 CRUD 和控制台重载的全局刷新。
- 修复部署、更新脚本运行时重启整个 nftables 服务的问题。
- 提供旧版项目规则迁移，同时保护 Docker 和外部对象。
- 不修改 API 路径、字段和业务调用顺序。

## 实施结果

- 项目只拥有并替换：
  - `inet dmz_webui_filter`
  - `ip dmz_webui_nat`
- 配置已移除 `flush ruleset`。
- 新增统一定向应用模块 `backend/firewall.py` 和命令入口
  `scripts/apply_nftables.py`。
- 后端写配置时先检查、定向原子应用，再原子持久化；失败不会写入半文件。
- 旧版迁移只在检测到 `ssh_ports` 或 `cn_ipv4` 特征集合后，清理白名单内的
  旧链与集合；不删除共享表。
- 迁移只读取旧版小写 `chain prerouting`，不会把 `DOCKER` 链中的 DNAT
  误迁移为用户规则。
- 部署和更新只启用 nftables 开机启动，不再运行时重启服务或完整加载规则集。
- 控制台按钮明确显示“应用项目规则”。

## 验证步骤与证据

已执行：

1. `python3 -m unittest discover -s backend/tests -v`
   - 11 项通过。
   - 覆盖所有权拒绝、全局 flush 拒绝、定向批次、迁移白名单、嵌套集合替换、
     Docker DNAT 不迁移。
2. `python3 -m py_compile backend/firewall.py backend/main.py
   scripts/apply_nftables.py scripts/sync_nftables.py`
   - 通过。
3. `bash -n scripts/deploy.sh scripts/update.sh scripts/common.sh`
   - 通过。
4. `npm run build`
   - TypeScript 和 Vite 生产构建通过，890 个模块完成转换。
5. `git diff --check`
   - 通过。
6. 全仓库危险入口扫描
   - 生产代码不存在 `flush ruleset`、直接 `nft -f` 和
     `systemctl restart nftables`。
7. 隔离网络命名空间真实 nftables 验证
   - 在 nftables 1.0.2 中完成旧版对象迁移和项目表替换。
   - 迁移后 `ip nat DOCKER` 哨兵链仍存在。
   - 两个项目独占表存在，旧版 `cn_ipv4` 对象已清理。

## 结论

根因已消除：页面及脚本不再通过全局 ruleset 重载应用项目规则。DMZ WebUI
的运行时修改边界已限制到两个项目独占表，Docker/外部表不会进入替换批次。

## 剩余风险

- 尚未在真实部署服务器执行 Docker 容器连通性验收；隔离命名空间已验证规则
  对象边界，但不能替代目标机网络、Docker 版本和 iptables 后端组合。
- 旧版迁移仅保留旧 `prerouting` 中可识别的 DNAT、CN IP 集合和 SSL 规则；
  旧项目链中的非标准手工 input/forward 规则不会自动猜测归属。
- `npm ci` 报告现有依赖有 8 个漏洞（1 low、3 moderate、4 high）；本轮没有
  未经确认升级依赖。
- 前端产物有单个大于 500 kB 的 Vite chunk 警告，不影响本轮构建结论。

## 后续动作

- 在目标服务器部署前备份 `/etc/nftables.conf`、`nft list ruleset` 和
  `iptables-save`。
- 按归档计划中的真实环境矩阵逐项操作，并验证 Docker 链与容器连通性。
- 真实部署验收完成后新增部署联调报告。
