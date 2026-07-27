# nftables 所有权收敛与 Docker 规则保护计划

> 归档状态：已完成
>
> 归档时间：2026-07-27
>
> 替代文档：`docs/reports/REPORT-20260727-nftables-ownership-v1.md`

## 背景与根因

当前 `/etc/nftables.conf` 以 `flush ruleset` 开头，后端所有防火墙写操作、
SSL 代理写操作、控制台 nftables 重载以及部署/更新流程都会完整执行该文件。
在 iptables 使用 nf_tables 后端或 Docker 直接使用 nftables 后端时，这会删除
Docker 及其他程序创建的规则。

前端只负责调用 API，越界发生在后端运行时应用方式和部署脚本。

## 本轮范围

本轮必须完成：

- 将项目规则迁移到独占的 `inet dmz_webui_filter` 与
  `ip dmz_webui_nat` 表。
- 删除项目配置中的全局 `flush ruleset`。
- 新增统一的定向应用模块；运行时只替换上述两个项目表。
- 将防火墙 CRUD、CN IP 集合更新、SSL 代理 CRUD、控制台重载以及部署/更新
  接入统一应用模块。
- 迁移旧版项目对象时，只在检测到项目特征对象后删除旧链，不删除共享表。
- 增加外部表、Docker 模拟链保持不变的回归测试。
- 更新 README、进度和交接上下文。

本轮不做：

- 不管理或重启 Docker。
- 不修改 Docker、firewalld、ufw 或其他项目的规则。
- 不改变前端 API 路径、请求字段、响应字段和现有业务流程。
- 不引入第三方依赖。

## 模块与接口契约

新增 `backend/firewall.py`，职责仅限：

- 从配置文本提取并校验两个项目独占表。
- 查询项目独占表是否存在。
- 构造并执行只删除、重建项目独占表的 nftables 原子批次。
- 在明确启用迁移时，识别并清理旧版项目链。

公开接口：

```python
apply_owned_rules(config_text: str, *, migrate_legacy: bool = False) -> None
```

约束：

- 配置缺少任一项目表时拒绝应用。
- 配置包含非项目表时拒绝应用。
- 默认不得删除任何旧版或外部对象。
- 迁移清理只允许触及：
  - 检测到 `inet filter ssh_ports` 后的旧版 `input`、`forward`、`output`
    链和 `ssh_ports` 集合；
  - 检测到 `ip nat cn_ipv4` 后的旧版 `prerouting`、`postrouting`
    链和 `cn_ipv4` 集合。
- 不删除 `inet filter` 或 `ip nat` 表，避免伤及同表中的 Docker/外部链。

新增 `scripts/apply_nftables.py` 作为部署脚本入口，只调用上述模块，不复制实现。

## 持久化与运行时行为

- `/etc/nftables.conf` 继续作为持久化入口，但内容只声明项目独占表，不再全局清空。
- Web API 修改配置后，先定向应用新配置；应用失败则不覆盖持久化文件。
- 持久化写入使用同目录临时文件与 `os.replace`，避免半文件。
- 部署和更新只启用 nftables 开机启动，不再运行时重启整个 nftables 服务。
- 控制台“重载 nftables”改为定向重载项目表。

## 迁移策略

1. `sync_nftables.py` 从旧运行配置提取现有 DNAT 与 `cn_ipv4` 数据。
2. 将提取结果写入采用独占表的新配置。
3. 定向创建或替换项目独占表。
4. 只有检测到旧版特征集合时，才删除对应旧链和特征集合。
5. 共享表本身以及其中未列入白名单的链、集合和规则全部保留。

迁移失败时不得通过 `flush ruleset`、重启 Docker 或重启 nftables 兜底。

## 验证矩阵

自动检查：

- 配置不含 `flush ruleset`。
- 配置只声明两个项目独占表。
- 定向批次只删除两个项目独占表。
- 配置中出现第三方表时拒绝执行。
- 无旧版特征对象时不生成迁移清理命令。
- 有旧版特征对象时只清理白名单内的旧链与集合。
- Python 单元测试、Python 语法检查、Shell 语法检查、前端构建通过。

真实环境验收（需部署环境）：

1. 记录 `nft list ruleset`、`iptables-save` 与 Docker 容器连通性。
2. 分别执行防火墙新增/修改/删除、CN IP 更新、SSL 开启规则、SSL 关闭规则、
   SSL 删除、控制台 nftables 重载。
3. 每一步确认项目规则正确变化。
4. 每一步确认 Docker 链、外部哨兵表和容器连通性不变。

## 风险与回滚

- 旧部署可能手工修改了项目旧链。迁移会保留可识别 DNAT 和 `cn_ipv4`，
  但无法证明所有非标准手工规则都属于项目；因此只清理具有项目特征的旧对象，
  并在真实部署前备份 `/etc/nftables.conf` 和完整 ruleset。
- 当前工作区没有真实目标机网络命名空间，自动测试只能验证命令边界；
  Docker 连通性必须在部署环境验收。
- 回滚代码前应先保存当前 ruleset；不得用全局 flush 作为回滚动作。
