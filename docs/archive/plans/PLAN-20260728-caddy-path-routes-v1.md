> 归档状态：已完成；替代文档：
> `docs/reports/REPORT-20260728-caddy-site-routes-v1.md`；归档时间：2026-07-28。

# Caddy 域名与路径路由功能计划

## 背景与现状

当前 SSL 代理只支持为每条规则创建独立监听端口：

```caddyfile
example.com:9443 {
    reverse_proxy 127.0.0.1:9091
}
```

主站点只包含 `/admin*`、`/assets*` 和根路径跳转，不能配置独立域名或路径：

```text
https://www.silvericekey.top/headscale
  -> 127.0.0.1:9091

https://www.silvericekey.top/derper.json
  -> 静态文件
```

另外，部署/更新脚本会从 shell 模板重新生成基础 Caddyfile，未读取动态 SSL
规则。新增路径路由时必须统一 Caddyfile 生成入口，避免更新后动态规则丢失。

用户已确认增加二级域名路由。最终规则由“访问域名 + 访问路径”共同定位。

## 已确认范围

### 页面

在现有“SSL 代理”页面增加两个管理分区：

- 端口代理：保留现有能力。
- 站点路由：新增域名与路径能力。

站点路由类型：

1. 反向代理
2. 静态文件

### 反向代理规则

字段：

- 访问域名，例如 `headscale.silvericekey.top`
- 访问路径，例如 `/` 或 `/headscale`
- 是否启用 SSL
- 目标 IP/主机，例如 `127.0.0.1`
- 目标端口，例如 `9091`
- 是否去掉访问路径前缀
- 备注

典型 Headscale 配置：

```text
headscale.silvericekey.top + /
  -> 127.0.0.1:9091
```

非根路径代理匹配路径本身及其子路径：

```text
/headscale
/headscale/*
```

“去掉前缀”只对非根路径生效。启用时，上游看到 `/` 和后续相对路径；
关闭时，上游保留原始 `/headscale...` URI。

### 静态文件规则

字段：

- 访问域名，例如 `www.silvericekey.top` 或 `static.silvericekey.top`
- 精确访问路径，例如 `/derper.json`
- 是否启用 SSL
- 备注

安全边界：

- 每条规则创建项目专属目录：
  `/var/lib/dmz-webui/caddy-static/<rule-id>/`。
- 页面显示该规则的实际存放目录。
- 访问 `/derper.json` 时，Caddy 读取：
  `/var/lib/dmz-webui/caddy-static/<rule-id>/derper.json`。
- 用户通过系统命令、SCP 或其他运维方式把文件放入该目录；本轮不增加上传。
- 不允许用户填写任意服务器绝对路径，避免借 Caddy 暴露系统文件。
- 删除规则时默认只撤销路由，保留静态目录，避免误删用户文件。

## 路径约束

- 必须以 `/` 开头。
- 禁止 `..`、查询字符串、片段、控制字符和空白。
- 主域名禁止覆盖 `/`、`/admin`、`/admin/*`、`/assets`、`/assets/*`。
- 同一域名下路径必须唯一。
- 同一域名下初版拒绝父子路径重叠，避免路由优先级产生隐式行为。
- 静态文件非根路径只做精确匹配；静态子域名配置 `/` 时，该托管目录下的
  文件可按相对 URL 路径访问，但不启用目录列表。
- 域名必须等于部署主域名或是其合法子域名。

## 数据与接口

配置文件：

```text
/etc/dmz-webui/site_routes.json
```

建议接口：

- `GET /api/caddy/site-routes`
- `POST /api/caddy/site-routes`
- `PUT /api/caddy/site-routes/{id}`
- `DELETE /api/caddy/site-routes/{id}`

统一模型字段：

- `route_type`: `proxy` / `static`
- `hostname`
- `path`
- `dest_host` / `dest_port`（仅 proxy）
- `strip_prefix`（仅非根 proxy）
- `ssl_enabled`
- `static_directory`（后端只读返回，仅 static）
- `comment`

## Caddy 生成与事务

- 按 hostname 分组生成 Caddy 站点；同一域名的主站点和自定义路径合并，
  独立子域名生成独立站点。
- 将主站点、端口代理和站点路由集中到一个 Python 生成模块。
- 后端保存时执行：
  1. 构建候选 Caddyfile。
  2. `caddy validate`。
  3. 原子写入并 reload。
  4. 成功后提交 JSON。
  5. 任一步失败则恢复 Caddyfile 和规则。
- 部署/更新调用同一生成入口，不再用 shell 模板覆盖动态规则。
- 站点路由复用现有主站点 443/8443，不新增 nftables 端口。

### TLS 与 DNS

- 二级域名启用 SSL 时，在标准 443 模式下使用 Caddy Automatic HTTPS，
  自动申请并续签公网受信任证书。
- 二级域名关闭 SSL 时，生成 `http://<hostname>` 站点。
- 同一二级域名下的所有路径必须使用相同 SSL 设置。
- 主域名路径沿用主站点 SSL 设置，不允许单条路径覆盖。
- 用户必须提前把子域名 DNS 解析到该服务器。
- 自动证书要求公网 80/443 可达。
- 非标准 8443 模式不提供二级域名公网证书自动申请；启用 SSL 的二级域名
  路由仅允许在标准 443 模式创建。

## 验收

- `headscale.<主域名>/` 正确转发到目标服务。
- 普通 `/headscale` 和 `/headscale/*` 路由仍支持前缀保留/去除。
- 前缀保留/去除两种行为有生成配置测试。
- 主域名或静态子域名的 `/derper.json` 精确读取托管目录中的同名文件。
- `/admin`、`/assets` 和根跳转保持不变。
- 路径冲突、非法路径和任意系统路径输入被拒绝。
- Caddy 校验/reload/配置或文件保存失败均完整回滚。
- 更新流程后，端口代理与路径路由均保留。
- 后端全量测试、Caddy validate、前端构建通过。

## 已确认与实现假设

- 已确认支持二级域名反向代理。
- 已确认二级域名启用 SSL 时由程序自动申请并续签证书。
- 已确认静态文件只需要访问地址和存放位置，本轮不做页面上传。
- 静态目录固定在项目专属根目录下，不接受任意绝对路径。
- 删除静态规则保留目录和文件。
- 反向代理提供“去掉路径前缀”开关，非根路径新建规则默认启用。
