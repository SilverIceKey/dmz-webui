# 本机端口开放功能计划

> 归档状态：已完成
> 替代文档：`docs/reports/REPORT-20260727-local-port-open-v1.md`
> 归档时间：2026-07-27

## 背景

当前防火墙页面只管理 `prerouting` 链中的 DNAT 端口转发。项目的 `input`
链默认策略为 `drop`，除部署时固定端口和启用 SSL 的 Caddy 监听端口外，
没有供用户动态放行宿主机服务端口的入口。

## 已确认需求

- 防火墙页面增加规则类型：
  - 端口转发
  - 本机端口开放
- 两类规则在界面和 nftables 行为上明确区分。

## 行为与接口契约

### 端口转发

- 保持现有 `/api/nftables/rules` 接口。
- 保持 `prerouting dnat` 行为和现有字段不变。

### 本机端口开放

- 新增模型字段：
  - `port`
  - `protocol`：`tcp`、`udp`、`both`
  - `whitelist_type`：`all`、`cn`、`abroad`、`custom`
  - `whitelist_ips`
  - `comment`
- 新增接口：
  - `GET /api/nftables/open-ports`
  - `POST /api/nftables/open-ports`
  - `PUT /api/nftables/open-ports/{protocol}/{port}`
  - `DELETE /api/nftables/open-ports/{protocol}/{port}`
- 规则写入 `inet dmz_webui_filter` 的 `chain input`：

```nft
ip saddr @cn_ipv4 tcp dport 19262 accept # local-open:Portainer
```

- `local-open` 标记用于区分项目固定放行、SSL 代理放行和用户本机端口规则。

### 大陆 IP 集合边界

真实 `nft -c` 验证发现，现有 `cn_ipv4` 只定义在 `ip dmz_webui_nat`，
不能被 `inet dmz_webui_filter` 的 input 链跨表引用。直接复用
`ip saddr @cn_ipv4` 会报集合不存在。

建议调整为：

- 在 `inet dmz_webui_filter` 中新增同名 `cn_ipv4` interval set。
- 两个 set 按 nftables 表作用域隔离，不是跨表共享对象。
- 大陆 IP 更新同时替换 filter 与 NAT 两个 set 的元素。
- 部署同步从现有 NAT 集合读取一次元素，同时填充两个项目 set。
- 不移动现有 NAT 链和 set，不改变 DNAT 主链路。

该调整属于项目独占表内部的数据结构扩展，已于 2026-07-27 经用户确认。

### 冲突规则

- 同一外部端口不得同时属于端口转发、SSL 代理或本机端口开放。
- `both` 与任一 TCP/UDP 同端口视为冲突。
- 编辑时排除正在编辑的原规则。
- 删除仅匹配带 `local-open` 标记的规则，不触碰固定放行和 SSL 规则。

## 前端

- 防火墙页面增加规则类型筛选和表单类型选择。
- 选择“端口转发”时显示目标 IP、目标端口。
- 选择“本机端口开放”时隐藏目标字段。
- 卡片明确显示“转发”或“本机开放”及对应目标。

## 范围边界

- 不自动把 DNAT 规则转换成本机开放规则。
- 不修改 Caddy/SSL 的代理流程。
- 不启用 `route_localnet`，不把 DNAT 到 `127.0.0.1` 作为本机开放方案。
- 不修改项目外 nftables 表、Docker 链或系统其他防火墙对象。
- 不负责启动或修改本机业务服务；直接开放时服务仍须监听公网网卡或
  `0.0.0.0`。

## 实施步骤

1. 用户确认 filter 表大陆 IP 集合方案。
2. 增加双表集合更新、部署同步及语法回归测试。
3. 完成本机开放后端模型、解析、增删改查和冲突校验。
4. 完成前端类型、API 和防火墙页面交互。
5. 更新 README、进度和交接上下文。
6. 执行后端全量测试、生成配置 `nft -c`、前端构建和差异检查。
7. 完成后新增报告并归档本计划。

## 验收标准

- 新增本机 TCP、UDP、TCP/UDP 规则后，input 链生成正确 accept 规则。
- 白名单前缀与端口转发语义一致。
- 编辑和删除只影响目标本机开放规则。
- 固定 SSH/WebUI 放行、SSL 代理规则及 Docker/外部对象保持不变。
- 跨端口转发、SSL、本机开放的冲突请求返回明确的 400。
- 前端可新增、编辑、删除并区分两类规则。
- 后端全量测试、nftables 语法检查和前端构建通过。
