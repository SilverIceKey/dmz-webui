# 规则保存/删除误报事务修复报告

## 背景

真实使用中，前端保存和删除提示失败，但刷新后规则已经变化。当前工作区无法访问
部署服务器 journal，因此本轮针对代码中能够直接证明的状态不一致与连接中断路径
进行根因修复。

## 根因

- SSL CRUD 在应用 Caddy/nftables 前先保存 JSON。后续失败会返回错误，但刷新列表
  仍能读取已经保存的候选规则。
- Caddy reload 失败时会在当前 API 请求内 restart Caddy，可能切断当前响应。
- 普通端口转发只改变 NAT，旧实现仍替换 filter/input 表，扩大了对当前连接的影响。
- SSL 关闭的普通转发仍添加 input accept，规则职责错误且导致额外 filter 变更。

## 修复

- SSL 规则、Caddy 和 nftables 改为候选配置事务：
  - 先生成并校验候选配置；
  - 运行态全部应用成功后才保存 SSL JSON；
  - 任一步失败恢复旧 Caddy、旧 nftables 和旧 JSON。
- Caddy 仅 graceful reload，失败直接进入事务回滚，不再 fallback restart。
- nftables 应用器比较新旧配置，只替换发生变化的项目独占表。
- SSL 关闭时只生成 DNAT，不再添加 input accept。
- 失败接口返回明确的“旧配置已恢复”错误。

## 验证证据

- `python3 -m unittest discover -s backend/tests -v`
  - 20 项通过。
  - 覆盖 Caddy reload 失败、JSON 写入失败、事务回滚、成功提交顺序、普通 CRUD
    成功响应、只替换变化表、SSL 关闭不开放 input。
- Python 语法、Shell 语法和 `git diff --check` 通过。
- `npm run build` 通过，890 个模块完成转换。
- 隔离 nftables 真实验证：
  - 在 filter/input 注入哨兵规则；
  - 执行仅改变 NAT 的定向应用；
  - 哨兵规则仍存在，证明 filter/input 未被重建。

## 结论

代码中“状态已落盘但接口失败”和“当前请求内重启 Caddy”的确定性根因已消除。
普通端口转发保存/删除也不再触及没有变化的 filter/input 表。

## 剩余风险

- 尚未取得原失败请求的真实 journal 和浏览器 Network 状态，无法证明部署机没有
  额外的代理超时、权限或 systemd 配置问题。
- 需要部署新版本后再次执行保存/删除，并采集 HTTP 状态和服务日志完成实机验收。
- 前端构建仍有单 chunk 大于 500 kB 的既有警告。
