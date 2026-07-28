# 动态站点标题与页签标题实现报告

## 背景

前端登录页、四个页面导航栏和浏览器 `<title>` 均硬编码为 `DMZ WebUI`。
现有部署配置已经支持域名、Caddy、ACME 邮箱和备案号，但不能在更新时修改
站点品牌标题。

## 范围

- 增加独立的站点标题和浏览器页签标题。
- 部署与更新脚本交互配置并持久化。
- 登录页和所有导航栏使用站点标题。
- 浏览器标签页使用页签标题。
- 保留旧配置兼容和接口失败 fallback。
- 不修改导航路径、登录流程、页面布局或后端鉴权。

## 实现

配置层新增：

- `DMZ_SITE_TITLE`
- `DMZ_TAB_TITLE`

`scripts/common.sh` 负责统一校验、交互输入、写入
`/etc/dmz-webui/install.conf` 和 systemd override。`deploy.sh` 与
`update.sh` 原本就复用该入口，因此两条链路行为一致。后续修复已把公网与
Caddy、页面标题、备案拆为三个独立确认分组；只选择修改页面标题即可。标题
输入回车保留当前值，输入 `-` 恢复 `DMZ WebUI`。

后端公开配置接口新增 `site_title` 和 `tab_title`。环境变量为空、超长或
包含不可打印字符时回退默认值。

前端增加单一 PublicConfig Context，在应用入口加载一次公开配置并设置
`document.title`。登录页、备案号和导航栏品牌从同一 Context 读取，避免每个
页面独立请求或维护默认值。

## 验证步骤与证据

已执行：

1. `python3 -m unittest discover -s backend/tests -v`
   - 54 项通过。
   - 覆盖标题 Unicode 输入、空值、超长、换行/引号注入、首尾空白处理、
     默认值恢复、配置持久化和公开接口返回。
2. `npm run build`（`frontend`）
   - TypeScript 与 Vite 生产构建通过，892 个模块完成转换。
3. `python3 -m py_compile backend/main.py`
   - 通过。
4. `bash -n scripts/common.sh scripts/deploy.sh scripts/update.sh`
   - 通过。
5. 使用 `bash -uo pipefail` 调用 `prompt_title_config`：
   - 修改标题成功。
   - 输入 `-` 恢复默认值成功。
6. `git diff --check`
   - 通过。

未执行：

- 目标服务器真实 `update.sh` 交互。
- systemd daemon-reload、服务重启和浏览器人工验收。

## 结论

站点可见标题和浏览器页签标题已从硬编码拆分为两个安全、可持久化配置。
更新脚本可以修改并复用配置，旧部署无需迁移即可使用默认标题。

## 剩余风险

- 需要目标服务器联调确认已有配置文件和 systemd override 的实际升级结果。
- 浏览器首次加载公开配置前会短暂使用静态 fallback `DMZ WebUI`，接口返回后
  更新为配置值，这是为接口失败保留可用性的预期行为。
- 前端存在既有 chunk 大小警告，不影响本轮构建通过结论。

## 后续动作

- 在目标服务器执行一次重新配置更新并记录页面验收证据。
- 再执行一次复用配置的更新，确认标题不会恢复默认值。
