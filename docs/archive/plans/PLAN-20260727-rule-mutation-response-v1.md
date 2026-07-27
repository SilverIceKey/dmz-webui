# 规则保存/删除误报事务修复计划

> 归档状态：已完成
>
> 归档时间：2026-07-27
>
> 替代文档：`docs/reports/REPORT-20260727-rule-mutation-response-v1.md`

## 已确认问题

- SSL CRUD 先写 `ssl_proxy_rules.json`，再生成 Caddy 配置并应用 nftables。
  后续步骤失败时接口返回失败，但刷新列表会读到已经写入的 JSON。
- `_reload_caddy` 在 reload 失败后执行 restart。该调用位于用户请求内，restart
  可能切断承载当前 API 响应的 Caddy 连接。
- 当前工作区不是部署服务器，无法取得当次 journal；本轮只修复上述代码可证实
  的状态顺序和连接中断问题，不假定未知部署错误。

## 修复范围

- SSL 新增、修改、删除改为统一事务：
  1. 基于候选规则生成 Caddy 与 nftables 候选配置；
  2. 预先校验 Caddy 配置和 nftables 配置；
  3. 应用候选配置；
  4. 全部成功后才持久化 SSL JSON；
  5. 任一步失败时恢复旧 Caddy、旧 nftables 和旧 JSON。
- Caddy 只允许 graceful reload；禁止 API 请求内 fallback restart。
- 普通端口转发只替换实际变化的 NAT 表，不重建承载当前连接的 filter/input 表。
- SSL 关闭时只生成 DNAT，不再额外添加无效的 input accept 规则。
- 普通 nftables CRUD 保持“应用成功后原子持久化”的既有顺序。
- API 路径、字段和成功响应保持不变。

## 接口与模块边界

- `_apply_ssl_proxy_rules(candidate_rules)` 接收候选规则，不再隐式读取已经保存的
  JSON。
- Caddy 配置生成拆为纯渲染函数与原子写入函数。
- Caddy 校验使用 `caddy validate --config <temp> --adapter caddyfile`。
- `_reload_caddy()` 失败时直接抛错，由事务层处理回滚。
- 不在前端捕获后把失败强行解释为成功。

## 验证

- SSL create/update/delete 成功时返回原有成功响应并持久化候选规则。
- nftables 应用失败时 JSON 与 Caddy 保持旧状态。
- Caddy reload 失败时不调用 restart，并恢复旧状态。
- 普通 nftables CRUD 成功响应回归。
- Python 单测、Python/Shell 语法、前端生产构建、危险命令扫描通过。

## 未覆盖

- 真实部署机的 Caddy/systemd/nftables 组合需部署后通过 journal 和浏览器 Network
  面板验收。
