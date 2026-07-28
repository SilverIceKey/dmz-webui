> 归档状态：已完成；替代文档：
> `docs/reports/REPORT-20260728-route-base-domain-v1.md`；归档时间：
> 2026-07-28。

# 站点路由基础域名与错误提示修复计划

## 当前状态

- 状态：配置、兼容和错误展示修复已实现并完成本地验证。
- 确认时间：2026-07-28。

## 复现

当前 WebUI 域名：

```text
DMZ_DOMAIN=www.silvericekey.top
```

新增站点路由：

```text
hostname=headscale.silvericekey.top
path=/
dest_host=127.0.0.1
dest_port=9091
```

页面提示：

```text
保存失败: [object Object]
```

## 根因

### 域名校验

当前 `SiteRouteCreate.validate_hostname` 只接受：

```text
hostname == DMZ_DOMAIN
hostname endswith "." + DMZ_DOMAIN
```

因此配置 `www.silvericekey.top` 时只允许：

```text
www.silvericekey.top
*.www.silvericekey.top
```

`headscale.silvericekey.top` 是 `www.silvericekey.top` 的同级主机名，会在进入
Caddy 校验前被 FastAPI/Pydantic 以 422 拒绝。

### 错误展示

FastAPI 422 的 `detail` 是错误对象数组。前端用字符串加法直接拼接该数组，
JavaScript 将对象转换成 `[object Object]`，真实字段和错误消息被隐藏。

同样的错误拼接模式还存在于 SSL 端口代理、防火墙、服务重载等入口，需要
使用一个公共格式化函数，不能只修站点路由。

## 建议配置模型

保留现有：

```text
DMZ_DOMAIN=www.silvericekey.top
```

它只表示 WebUI/Caddy 主站地址。

新增：

```text
DMZ_ROUTE_DOMAIN=silvericekey.top
```

它表示站点路由允许使用的基础域名。允许：

```text
silvericekey.top
*.silvericekey.top
```

其中包括 `www.silvericekey.top` 和 `headscale.silvericekey.top`。

## 兼容策略

- 新配置显式保存到 `/etc/dmz-webui/install.conf` 和 systemd override。
- `deploy.sh`/`update.sh` 的“公网与 Caddy 配置”分组询问路由基础域名。
- 没有 `DMZ_ROUTE_DOMAIN` 的历史配置：
  - 当 `DMZ_DOMAIN` 以 `www.` 开头时，默认去掉 `www.`。
  - 其他情况默认等于 `DMZ_DOMAIN`。
- 这样当前 `www.silvericekey.top` 升级后默认允许
  `headscale.silvericekey.top`，普通 `example.com` 部署保持原行为。
- WebUI 的 `/admin`、`/assets` 和根路径保留规则仍只绑定
  `DMZ_DOMAIN`，不能误套到基础域名或其他子域名。
- 二级域名 HTTPS 仍要求标准 443 模式、DNS 指向服务器且公网 80/443 可达。

## 公开配置与页面

`GET /api/public-config` 增加只读字段：

```text
route_domain
```

站点路由表单在域名输入框下显示：

```text
允许 <route_domain> 及其子域名
```

不在前端自行校验公共后缀，最终校验仍由后端负责。

## 错误格式化

新增单一前端工具处理：

- FastAPI `detail` 字符串。
- FastAPI 422 `detail[]`，显示字段路径和 `msg`。
- 普通 Axios/网络错误。
- 未知对象安全序列化。

建议 422 展示：

```text
保存失败: hostname: hostname must use the configured route domain
```

SSL 代理、防火墙、站点路由、服务操作和登录错误统一复用，不复制格式化逻辑。

## 验收

- `DMZ_DOMAIN=www.silvericekey.top` 时默认推导
  `DMZ_ROUTE_DOMAIN=silvericekey.top`。
- `headscale.silvericekey.top` 校验通过。
- `foreign.example.com` 校验拒绝。
- `headscale.www.silvericekey.top` 仍在允许范围内。
- 主站保留路径只对 `www.silvericekey.top` 生效。
- 部署/更新持久化并复用路由基础域名。
- 422 错误显示字段和消息，不再出现 `[object Object]`。
- 其他页面现有字符串错误仍正常显示。
- 后端全量测试、脚本交互回放和前端生产构建通过。

## 已确认

- 新增 `DMZ_ROUTE_DOMAIN`，并对以 `www.` 开头的历史主域名默认去掉
  `www.` 作为路由基础域名。
