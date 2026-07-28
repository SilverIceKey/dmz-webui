# 站点路由基础域名与错误提示进度

## 当前状态

- 状态：根因修复与本地自动验证完成，等待目标服务器更新和真实路由验收。
- 当前结论：`www.silvericekey.top` 部署默认允许创建
  `headscale.silvericekey.top`，422 错误不再显示 `[object Object]`。

## 最近关键结论

- 新增 `DMZ_ROUTE_DOMAIN`，与 WebUI 主站 `DMZ_DOMAIN` 分离。
- 历史主站以 `www.` 开头时默认去掉前缀作为路由基础域名；其他配置保持原值。
- 域名校验允许基础域名本身及其子域名，拒绝外部域名。
- `/admin`、`/assets` 和根路径保留规则仍只绑定 WebUI 主站。
- 部署/更新的公网与 Caddy 分组可查看和修改路由基础域名。
- 公开配置返回 `route_domain`，前端站点路由表单显示允许范围。
- 新增公共错误格式化工具，覆盖登录、防火墙、SSL 端口代理、站点路由和服务
  重载。
- 后端 57 项测试通过，前端生产构建通过。

## 下一步

- 目标服务器更新后确认 systemd 环境包含
  `DMZ_ROUTE_DOMAIN=silvericekey.top`。
- 新建 `headscale.silvericekey.top` 到 `127.0.0.1:9091` 的路由并检查 Caddy
  配置、证书和访问结果。
- 人工触发一次非法域名校验，确认页面显示字段与具体消息。

## 阻塞项

- 当前开发环境不是目标服务器，无法验证真实 DNS、ACME 和 Caddy reload。

## 未证实风险

- 目标服务器第一次仍可能运行旧版更新脚本；代码同步完成后需再次运行最新版
  脚本，才能使用新增的基础域名交互。
- 当前站点反代是 HTTP 层 Caddy `reverse_proxy`，不提供原始 TCP/SNI 透传。
