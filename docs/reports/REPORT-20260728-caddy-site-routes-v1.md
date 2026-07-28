# Caddy 域名与路径路由实现报告

## 背景

原 SSL 代理只能在独立外部端口上创建 Caddy 代理，不能把
`headscale.<主域名>/` 转发到本机服务，也不能通过受控目录提供
`derper.json` 等静态文件。部署和更新仍有独立 shell Caddyfile 模板，存在
覆盖运行时动态规则的风险。

## 范围

- 在 SSL 代理页面增加“域名与路径路由”。
- 支持反向代理和静态文件两种路由。
- 支持主域名及其子域名，支持根路径与非根路径。
- 二级域名可选择 HTTPS 或 HTTP。
- 统一部署、更新和运行时 Caddyfile 生成入口。
- 不增加文件上传，不接受任意静态目录，不开放新的业务端口。

## 实现

后端新增 `/api/caddy/site-routes` CRUD。候选规则先经过域名、路径、保留路径、
同域 SSL 一致性和路径重叠校验，再生成并校验完整 Caddyfile；reload 成功后
才提交 JSON。失败时恢复原 Caddyfile，静态目录不会被破坏。

二级域名启用 SSL 时生成无显式 `tls` 的 Caddy hostname 站点，触发 Caddy
Automatic HTTPS。Caddy负责首次签发和后续续签；已有可选 ACME 邮箱继续通过
全局 Caddy 配置传入。关闭 SSL 时生成 `http://<hostname>`。

自动 HTTPS 的外部前提是：

- 标准 443 部署模式；
- 子域名 DNS 已指向目标服务器；
- 公网 80/443 能到达 Caddy。

静态文件规则固定映射到
`/var/lib/dmz-webui/caddy-static/<规则 ID>/`。页面返回并显示该目录，删除
规则只删除路由配置，不删除文件。

## 验证步骤与证据

已执行：

1. `python3 -m unittest discover -s backend/tests -v`
   - 48 项通过。
   - 覆盖域名和路径校验、Caddy matcher 注入拒绝、路径冲突、HTTPS/HTTP
     子域名、ACME 邮箱、Headscale 代理头、前缀去除、静态目录、事务提交及
     reload 回滚。
2. `npm run build`（`frontend`）
   - TypeScript 与 Vite 构建通过，890 个模块完成转换。
3. `python3 -m py_compile backend/main.py backend/caddy_routes.py
   scripts/generate_caddyfile.py`
   - 通过。
4. `bash -n scripts/common.sh scripts/deploy.sh scripts/update.sh`
   - 通过。
5. `git diff --check`
   - 通过。

未执行：

- 真实 `caddy validate`：当前开发环境未安装 Caddy。
- 公网 ACME 签发/续签：需要目标服务器、真实 DNS 和公网 80/443。
- Headscale 与静态文件浏览器/客户端联调：需要部署后的真实服务和文件。

## 结论

项目现已能用独立子域名或主域名路径代理本机服务，并能从项目受控目录提供
静态文件。子域名开启 SSL 后由 Caddy 自动申请和续签证书；部署和更新不会再
用基础模板覆盖动态 Caddy 规则。

## 剩余风险

- 自动证书功能依赖外部 DNS 与网络条件，只有目标服务器联调后才能最终验收。
- Headscale 的客户端长连接和协议行为尚未实机确认。
- 前端构建存在既有 chunk 大小警告，不影响本轮构建通过结论。

## 后续动作

- 更新目标服务器，确认 `caddy validate`、reload 和日志无错误。
- 检查 Caddy 证书存储和 journal，确认子域名证书签发成功。
- 使用真实 Headscale 客户端和静态文件完成外部访问验收。
