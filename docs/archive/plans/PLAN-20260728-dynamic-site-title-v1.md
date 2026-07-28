> 归档状态：已完成；替代文档：
> `docs/reports/REPORT-20260728-dynamic-site-title-v1.md`；归档时间：
> 2026-07-28。

# 动态站点标题与页签标题计划

## 当前状态

- 状态：用户已确认字段语义与展示范围，实现与本地验证已完成。
- 确认时间：2026-07-28。

## 需求理解

新增两个独立配置：

1. 站点标题
   - 替换登录页主标题中的 `DMZ WebUI`。
   - 替换登录后各页面导航栏左侧的 `DMZ WebUI`。
2. 页签标题
   - 设置浏览器标签页的 `document.title`。
   - `frontend/index.html` 保留 `DMZ WebUI` 作为接口加载前和接口失败时的
     fallback。

默认值均为 `DMZ WebUI`，避免未配置或旧版本升级时出现空标题。

## 配置与接口

建议增加环境变量：

- `DMZ_SITE_TITLE`
- `DMZ_TAB_TITLE`

配置链路：

1. `scripts/common.sh` 的交互配置收集两个标题。
2. 保存到 `/etc/dmz-webui/install.conf`。
3. 写入 `dmz-webui.service.d/override.conf`。
4. `scripts/deploy.sh` 与 `scripts/update.sh` 均复用该配置链路。
5. `GET /api/public-config` 增加：
   - `site_title`
   - `tab_title`

`update.sh` 检测到已有配置时继续使用当前“是否复用”逻辑：

- 选择复用：沿用已有标题。
- 选择不复用：交互式修改两个标题和其他部署配置。

## 前端边界

- 在应用入口加载一次公共配置，设置 `document.title`。
- 通过 React Context 或等价的单一配置入口向登录页和导航栏提供
  `site_title`，不在多个页面重复请求接口。
- 现有四个页面重复实现了 Navbar。本轮只提取标题展示所需的最小公共组件，
  不改变导航路径、退出行为或页面布局。
- 公共配置请求失败时使用 `DMZ WebUI`，登录、路由和其他功能不受影响。

## 输入约束

- 两个标题去除首尾空白。
- 环境变量为空时恢复默认值 `DMZ WebUI`。
- 交互输入直接回车保留当前值，输入 `-` 恢复默认值。
- 拒绝换行和控制字符。
- 建议限制为最多 80 个 Unicode 字符，避免异常配置撑坏导航栏或 systemd
  环境变量文件。
- React 以普通文本渲染，不使用 HTML 注入。

## 验收

- 首次部署可分别输入站点标题与页签标题。
- `update.sh` 选择重新配置后可修改两个标题。
- 更新后登录页、所有导航栏显示新的站点标题。
- 浏览器页签显示新的页签标题。
- 旧配置中没有新字段时自动使用 `DMZ WebUI`。
- 空输入、控制字符和超长输入按约束处理。
- ICP 备案号仍由同一次公共配置请求正常显示。
- 后端全量测试、部署配置测试和前端生产构建通过。

## 已确认

1. “title”是登录页主标题和登录后导航栏左侧标题。
2. `deploy.sh` 与 `update.sh` 都支持配置并持久化。
