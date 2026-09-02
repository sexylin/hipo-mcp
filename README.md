# HiPo Work MCP Server

[![MCP Server](https://img.shields.io/badge/MCP-Server-blue)](https://modelcontextprotocol.io)
[![OAuth 2.0](https://img.shields.io/badge/Auth-OAuth2.0-green)](https://oauth.net/2/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

将 HiPo Work 招聘平台工具暴露为 MCP (Model Context Protocol) 工具，供 AI Agent 调用。支持 OAuth 2.0 自动授权，无需手动配置 API Key。

**适用客户端：** Claude Desktop、Hermes Agent、Cursor、VS Code、Cline 等所有支持 MCP 的客户端

---

## 功能一览

HiPo Work 是一个面向 AI Agent 的招聘平台：

- **求职者**：通过 Agent 导入结构化简历（`import_resume`），可保留工作经历、项目经历、教育经历、技能、证书和语言能力
- **招聘方**：通过 Agent 发布岗位（`publish_job`）、智能匹配候选人（`match_candidates`）、市场分析（`market_analysis`）
- **自动认证**：OAuth 2.0 授权码流程，无需手动管理 Key

---

## 快速开始

### 1. 配置 MCP 客户端

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "hipo": {
      "url": "https://mcp.hipowork.com/mcp"
    }
  }
}
```

**Hermes Agent** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  hipo:
    url: "https://mcp.hipowork.com/mcp"
```

**VS Code / Cursor** MCP 配置面板，添加：

```
https://mcp.hipowork.com/mcp
```

### 2. 首次授权

1. 首次调用工具时，自动打开浏览器 `https://mcp.hipowork.com/authorize`
2. 输入邮箱 → 获取验证码 → 输入验证码
3. 授权完成，自动返回客户端，**后续无需再操作**

> Token 30 天有效，自动刷新，无需手动配置 API Key。

> **已登录用户免重复验证**：若你已在 Web 端（hipowork.com）登录，登录态会自动同步到授权域。之后从 Agent 发起授权时，授权页直接显示「确认授权」按钮，无需再次输入邮箱和验证码（隐藏 iframe + 一次性 HMAC 票据，60 秒时效，Cookie 90 天）。

---

## 工具列表

| 工具名 | 说明 | 认证 |
|--------|------|------|
| `send_verification_code` | 发送邮箱验证码（注册/登录前调用） | 公开 |
| `register_or_login` | 邮箱验证码注册/登录 | 公开 |
| `publish_job` | 发布招聘岗位（结构化条件） | employer |
| `match_candidates` | 匹配候选人（含评分明细+工作经历） | employer |
| `match_job_requirement` | 按岗位 ID 自动匹配候选人 | employer |
| `search_candidates` | 自然语言搜索候选人 | employer |
| `get_stats` | 平台统计数据 | employer |
| `market_analysis` | 技能/行业人才供需分析 | employer |
| `import_resume` | 导入简历（Agent 解析后传入结构化数据，包含工作/项目/教育经历） | candidate |

---

## 认证机制

### OAuth 2.0（唯一推荐方式）

HiPo Work 自己作为 OAuth Authorization Server：

- 使用 Authorization Code + PKCE（S256）
- 用户在 HiPo Work 授权页面完成邮箱验证码登录
- 用户明确授权当前 MCP 客户端
- 客户端自动获得 HiPo Work access token 和 refresh token
- Access token 15 分钟有效，Refresh token 90 天，用于自动刷新
- 支持 token 吊销（`POST /revoke`）
- 用户不需要接收、复制或配置 API Key

首次登录时的流程：

```text
配置 MCP 地址
→ 客户端打开 HiPo Work 授权页
→ 输入邮箱和验证码
→ 确认角色及客户端权限
→ 自动返回 MCP 客户端
→ 后续自动使用 OAuth Token
```

### API Key

当前新用户流程不再创建或发送 API Key。此前的 API Key 代码仅作为历史数据兼容保留，不属于当前 MCP 接入方式。

---

## 部署

### 启动服务

```bash
# 安装
pip install fastmcp httpx uvicorn

# 启动
HIPO_BACKEND_URL=http://127.0.0.1:8000 \
HIPO_MCP_BASE_URL=https://mcp.hipowork.com \
uvicorn hipo_mcp.server:app --host 127.0.0.1 --port 8003
```

### Nginx 反代（必须配 HTTPS）

MCP 使用独立子域名，所有 MCP、OAuth 和 metadata 路由统一反代到 MCP 服务；新增路由无需逐条修改 nginx。

```nginx
server {
    listen 80;
    server_name mcp.hipowork.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mcp.hipowork.com;

    ssl_certificate /etc/letsencrypt/live/hipowork.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hipowork.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 300s;
    }
}
```

> ⚠️ MCP 通信包含用户凭证，必须使用 HTTPS。

---

## 本地开发

```bash
git clone https://github.com/sexylin/hipo-mcp.git
cd hipo-mcp
pip install -e .
```

---

## License

MIT