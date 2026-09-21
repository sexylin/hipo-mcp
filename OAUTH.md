# HiPo Work 原生 OAuth 改造说明

当前改造目标：HiPo Work 自己作为 OAuth Authorization Server。邮箱验证码只用于确认 HiPo Work 用户身份；MCP 客户端通过 Authorization Code + PKCE 获得 HiPo Work OAuth access/refresh token。

## 当前已实现

- `POST /api/v1/auth/register-or-login`：邮箱验证码注册/登录，只返回用户身份摘要。
- `POST /api/v1/auth/oauth/exchange`：受信任的 MCP 服务将已验证用户身份换成 HiPo OAuth token。
- `POST /api/v1/auth/oauth/refresh`：受信任的 MCP 服务刷新 OAuth token。
- 后端业务认证：识别带 `aud=hipo-work`、`auth_source=oauth`、`type=oauth_access` 的 Bearer Token。
- MCP OAuth 授权码兑换：向 Backend 获取原生 HiPo OAuth token。
- MCP 工具调用：使用 `Authorization: Bearer <HiPo OAuth access token>` 调用 Backend。
- MCP OAuth scope：`profile`、`candidate:read`、`candidate:write`、`employer:read`、`employer:write`。
- OAuth access token：默认 15 分钟。
- OAuth refresh token：默认 90 天。
- PKCE、redirect_uri 精确匹配、授权码一次性消费和 refresh token 轮换逻辑保留在 MCP OAuth 层。

## 环境变量

Backend 与 MCP 必须配置同一组签名和内部服务密钥；真实值只能放在服务端环境变量或密钥管理系统中：

Backend：

```text
OAUTH_SIGNING_KEY=<随机高强度密钥>
OAUTH_AUDIENCE=hipo-work
MCP_INTERNAL_SECRET=<随机高强度内部服务密钥>
```

MCP：

```text
HIPO_BACKEND_URL=http://127.0.0.1:8000
MCP_INTERNAL_SECRET=<与 Backend 相同的内部服务密钥>
HIPO_MCP_BASE_URL=https://mcp.hipowork.com
```

`OAUTH_SIGNING_KEY` 必须与 Backend 和 MCP 实际使用的签名方案一致。当前 MCP 通过 Backend 的 exchange/refresh 接口获得 Token，不应自行生成用户 Token。

## MCP 客户端流程

```text
MCP Client → /mcp
             ← 401 + Protected Resource Metadata
MCP Client → DCR /register
MCP Client → /authorize?code_challenge=...
用户       → HiPo Work 邮箱验证码登录
用户       → 确认客户端和角色权限
HiPo Work  → 回调客户端 redirect_uri?code=...&state=...
MCP Client → /token + code_verifier
MCP        → Backend /auth/oauth/exchange
Backend    → HiPo OAuth access_token + refresh_token
MCP Client → MCP initialize/tools/call，自动携带 Bearer Token
```

网页 Cookie 与 Agent Token 不共享；Agent 使用自己的 OAuth 授权结果。

## 重要限制

当前 OAuth client、authorization code、access token、refresh token 和 pending state 仍使用 MCP 进程内存保存，适合单进程测试，不适合重启恢复或多进程生产部署。正式上线前需要迁移到 Redis 或 PostgreSQL，并加入持久化 revocation/consent。

## 验证命令

Backend：

```bash
cd /Users/lintong/Documents/FlyBirds/FlyBirds-backend
./venv/bin/python3 -m py_compile app/core/oauth.py app/core/oauth_security.py app/core/security.py app/api/v1/oauth.py app/api/v1/auth.py app/main.py tests/test_oauth_tokens.py
./venv/bin/python3 -m unittest discover -s tests -v
```

MCP：

```bash
cd /Users/lintong/Documents/FlyBirds/hipo-mcp
python3 -m py_compile hipo_mcp/oauth.py hipo_mcp/routes.py hipo_mcp/server.py
```

若已安装项目依赖，可进一步执行：

```bash
.venv-oauth/bin/python -c 'import fastmcp,mcp; from hipo_mcp.server import mcp; import asyncio; print(asyncio.run(mcp.list_tools()))'
```

## 当前 Git 基线

改造前回滚标签：

```text
pre-native-oauth-20260828
```

该标签已推送到 Backend、Frontend、AI 和 MCP 四个仓库。

## 部署与扩容注意事项

### 单进程部署（当前生产配置，安全）

```ini
ExecStart=/home/ubuntu/hipo/hipo-mcp/venv/bin/uvicorn hipo_mcp.server:app --host 127.0.0.1 --port 8003
```

未指定 `--workers` 时 uvicorn 默认单 worker。此时 OAuth 状态（client 注册 /
auth_code / access_token / refresh_token / pending_auth）与验证码限流计数
均保存在进程内内存（`storage.py` 的 `MemoryStore`），单进程语义完全正确，
**无需配置 Redis**。

代价：`systemctl restart hipo-mcp`（部署、改配置、机器重启）会清空所有已签发
token，已授权的 AI 客户端需重新走一遍授权。收到"刚授权又要重新授权"的反馈时，
先确认是否刚重启过服务，再怀疑 bug。

### 扩容前必须配置 Redis

一旦加上 `--workers N`（N>1）或在负载均衡后挂多实例，未配 Redis 会同时触发：

1. **token 随机失效**：token 只写进其中一个 worker 的内存，请求落到其他 worker
   时 `verify_token` 查不到 → 授权成功后仍随机 401；
2. **授权码可被重复兑换**：`exchange_authorization_code` 靠 `auth_codes.pop()`
   保证一次性消费，多进程各自 pop 成功 → 同一 code 可换多次 token；
3. **登录中途 state 丢失**：GET /authorize 与 POST /authorize 落在不同 worker，
   `get_pending_auth` 返回空 → 用户看到"会话已过期，请重新授权"并从头上传；
4. **验证码限流失效**：限流桶各进程独立计数，配置"每分钟 5 次"在 4 worker 下
   实际变成每分钟最多 20 次，短信成本成倍放大。

扩容操作（代码无需改动，配好环境变量即自动切换 Redis 后端）：

```bash
sudo apt install -y redis-server && sudo systemctl enable --now redis-server
/home/ubuntu/hipo/hipo-mcp/venv/bin/pip install redis
# 在 systemd unit 的 [Service] 段加入：
#   Environment="HIPO_REDIS_URL=redis://127.0.0.1:6379/0"
sudo systemctl restart hipo-mcp
```

`oauth.py` 会检测 `STORE.redis_enabled` 并自动把全部 OAuth 状态与限流计数
切到 Redis，支持多副本共享。

### 401 日志的正常与异常

MCP 客户端在拿到 token 前会反复探测 `/mcp`，服务端如实回 401 并附
`WWW-Authenticate` 头引导其发起 OAuth 授权。这类 401 集中在"用户正在授权页
操作"的时间窗内，`/sso` 回调完成后即消失，属协议正常握手，不必处理。

需要排查的是另一类：**授权完成、token 有效期内仍持续 401**。单进程部署下
通常是刚重启过服务；多 worker 部署下则是未配 Redis（见上）。

