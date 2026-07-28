# 本机端口开放功能报告

## 背景

项目原有防火墙页面只生成 NAT prerouting DNAT。转发到内网主机的数据包会
经过 forward 链，但宿主机服务需要经过默认策略为 drop 的 input 链，原页面
没有动态放行入口。

## 范围

- 增加本机端口开放规则类型，与端口转发明确区分。
- 支持 TCP、UDP、TCP/UDP。
- 支持全部、大陆、境外和自定义 IP/CIDR 来源白名单。
- 增加本机开放 CRUD 接口和前端交互。
- 部署更新时保留本机开放规则。
- 不启动本机业务服务，不修改业务服务监听地址，不启用 `route_localnet`。

## 接口与规则

新增接口：

- `GET /api/nftables/open-ports`
- `POST /api/nftables/open-ports`
- `PUT /api/nftables/open-ports/{protocol}/{port}`
- `DELETE /api/nftables/open-ports/{protocol}/{port}`

规则写入项目独占 `inet dmz_webui_filter` 表的 input 链，并使用
`local-open` 标记，例如：

```nft
ip saddr @cn_ipv4 tcp dport 19262 accept # local-open:Portainer
```

删除和编辑只匹配该标记，不会删除 SSH、WebUI、SSL 代理或其他固定放行。

## 大陆白名单结构

实现过程中真实 `nft -c` 发现，原 `cn_ipv4` set 位于
`ip dmz_webui_nat`，不能被 `inet dmz_webui_filter` 跨表引用。

经用户确认后，两个项目独占表各自维护同名 `cn_ipv4` set：

- filter 表集合供本机开放规则使用。
- NAT 表集合供端口转发使用。
- 更新大陆 IP 时同时替换两份集合。
- 部署同步从现有配置读取集合元素并填充两份集合。

该方案没有移动 NAT 链，也没有改变现有端口转发路径。

## 冲突处理

同一外部端口不能同时用于：

- 本机端口开放
- DNAT 端口转发
- SSL 代理
- 项目固定 input 放行

编辑时排除正在编辑的原规则，避免自身误报冲突。

共用规则模型会校验自定义白名单的每一项为 IPv4/CIDR，并拒绝多行备注，
避免无效 nftables 文本和换行注入。

## 验证结果

已执行：

1. `python3 -m unittest discover -s backend/tests -v`
   - 36 项通过。
   - 覆盖本机开放生成/解析/删除、固定规则保护、大陆白名单、双集合更新、
     部署保留和跨类型冲突。
2. 完整配置真实语法检查：
   - 生成大陆白名单 TCP/UDP 本机开放规则。
   - 同时生成境外白名单 DNAT 规则。
   - 执行 `nft -c -f -` 通过。
3. `python3 -m py_compile backend/firewall.py backend/main.py
   scripts/apply_nftables.py scripts/sync_nftables.py`
   - 通过。
4. `bash -n scripts/deploy.sh scripts/update.sh scripts/common.sh`
   - 通过。
5. `npm run build`
   - TypeScript 与 Vite 生产构建通过，890 个模块完成转换。
6. `git diff --check`
   - 通过。

## 结论

本机端口开放已成为独立规则类型。它只操作项目 filter/input 链，并与 DNAT
端口转发、SSL 代理保持清晰边界；两类规则均可使用大陆等来源白名单。

## 剩余风险

- 尚未在目标服务器通过浏览器执行真实新增、编辑和删除。
- 尚未使用外部客户端验证大陆/境外地址命中效果。
- 本机开放只负责防火墙 accept。业务服务必须监听 `0.0.0.0` 或实际网卡；
  仅监听 `127.0.0.1` 的服务仍需 Caddy 代理或调整自身配置。
- 前端仍有既有的大于 500 kB chunk 警告，本轮未调整打包结构。

## 后续动作

- 部署后分别创建全部、大陆和自定义来源的本机开放规则。
- 核对 input 链、页面返回和外部连通性。
- 确认删除本机开放规则后固定 SSH/WebUI 与 SSL 规则保持不变。
- 确认 Docker 链和容器连通性不受影响。
