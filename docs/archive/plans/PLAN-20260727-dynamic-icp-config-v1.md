# 部署时动态备案号配置计划

> 归档状态：已完成
>
> 归档时间：2026-07-27
>
> 替代文档：`docs/progress/PROGRESS-20260727-login-icp-footer-v1.md`

## 目标

移除登录页硬编码备案号，改为部署时交互配置，并在更新和重启后持续生效。

## 配置契约

- 环境变量：`DMZ_ICP_NUMBER`
- 部署配置：`/etc/dmz-webui/install.conf`
- systemd drop-in：`/etc/systemd/system/dmz-webui.service.d/override.conf`
- 空值：不显示备案链接
- 有效格式：省份简称 + `ICP备` + 数字 + `号`，允许可选的 `-数字` 后缀

`deploy.sh` 和选择重新配置时的 `update.sh` 会提示输入；选择复用已有部署配置时
沿用原值。

## 接口契约

新增无需认证的只读接口：

```http
GET /api/public-config
```

响应：

```json
{
  "icp_number": "浙ICP备12345678号"
}
```

接口只暴露允许公开展示的备案号，不返回其他环境配置。

## 前端行为

- 登录页加载时请求公共配置。
- `icp_number` 非空时显示工信部备案链接。
- 请求失败或值为空时隐藏链接，不影响登录。
- 链接固定为 `https://beian.miit.gov.cn/`，新窗口安全打开。

## 影响范围

- `scripts/common.sh`
- `.env.example`
- `backend/main.py`
- `frontend/src/utils/api.ts`
- `frontend/src/pages/Login.tsx`
- 部署说明与交接文档

不修改认证接口、登录流程或其他页面。

## 验证

- Shell 语法检查。
- 备案号格式校验：有效、带后缀、空值、无效值。
- 公共接口仅返回备案号且无需认证。
- 前端生产构建通过。
- 源码不再硬编码实际备案号。
