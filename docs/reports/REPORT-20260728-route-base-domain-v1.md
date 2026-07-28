# 站点路由基础域名与错误提示修复报告

## 背景

目标服务器使用 `www.silvericekey.top` 部署 WebUI。创建
`headscale.silvericekey.top -> 127.0.0.1:9091` 时保存失败，页面只显示
`[object Object]`。

## 根因

后端把 `DMZ_DOMAIN` 同时作为 WebUI 主站和站点路由允许后缀，因此只接受
`www.silvericekey.top` 与 `*.www.silvericekey.top`。目标 hostname 在进入
Caddy 前被 Pydantic 422 拒绝。

前端直接将 FastAPI 422 的 `detail[]` 与字符串拼接，JavaScript 把错误对象
转换成 `[object Object]`，掩盖了实际的 hostname 校验消息。同样模式存在于
多个页面。

## 修复范围

- 新增 `DMZ_ROUTE_DOMAIN`。
- 部署配置、systemd override 和公网/Caddy 交互持久化该字段。
- 历史 `www.*` 主站默认去掉 `www.`，其他域名保持原值。
- 后端使用基础域名校验站点 hostname。
- 公开配置返回路由基础域名，表单显示允许范围。
- 公共前端工具统一格式化字符串、FastAPI 422 数组和网络错误。

WebUI 主站保留路径逻辑、Caddy 生成和事务顺序没有改变。

## 验证步骤与证据

已执行：

1. `python3 -m unittest discover -s backend/tests -v`
   - 57 项通过。
   - 覆盖 `www.` 默认推导、历史配置落盘、同级子域名允许、外部域名拒绝、
     主站保留路径和公开配置。
2. `npm run build`（`frontend`）
   - TypeScript 与 Vite 生产构建通过，893 个模块完成转换。
3. `python3 -m py_compile backend/main.py`
   - 通过。
4. `bash -n scripts/common.sh scripts/deploy.sh scripts/update.sh`
   - 通过。
5. `git diff --check`
   - 通过。

未执行：

- 目标服务器真实 `update.sh`、systemd 重启和 Caddy reload。
- `headscale.silvericekey.top` 的 DNS、ACME 签发和外部访问。
- 浏览器人工触发 422 的视觉验收。

## 结论

WebUI 主机名与路由 DNS 范围已分离。当前部署无需改成
`headscale.www.silvericekey.top`，升级后可使用
`headscale.silvericekey.top`；前端能展示实际校验错误。

## DERP/TCP 边界

本轮没有增加原始 TCP/SNI 转发。现有站点路由使用 Caddy HTTP
`reverse_proxy`。它支持普通 HTTP 与 WebSocket，但不等于 TCP/TLS
passthrough，也不处理 DERP 的 UDP STUN 端口。

## 剩余风险

- 真实证书申请仍依赖 DNS 指向本机及公网 80/443 可达。
- 如果 9091 运行的是 Tailscale `derper` 而不是普通 Headscale HTTP 服务，
  需要按 DERP 的独立端口和协议要求设计，不能把本轮 HTTP 路由当成 TCP/SNI
  透传。

## 后续动作

- 目标服务器升级并重新运行最新版更新脚本。
- 检查安装配置与 systemd override 后创建真实站点路由。
