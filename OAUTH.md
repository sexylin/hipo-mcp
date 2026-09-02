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
