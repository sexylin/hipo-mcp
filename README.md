# HiPo Work MCP Server

[![MCP Server](https://img.shields.io/badge/MCP-Server-blue)](https://modelcontextprotocol.io)
[![OAuth 2.0](https://img.shields.io/badge/Auth-OAuth2.0-green)](https://oauth.net/2/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

将 HiPo Work 招聘平台工具暴露为 MCP (Model Context Protocol) 工具，供 AI Agent 调用。支持 OAuth 2.0 自动授权，无需手动配置 API Key。

**适用客户端：** Claude Desktop、Hermes Agent、Cursor、VS Code、Cline 等所有支持 MCP 的客户端

---

## 功能一览

HiPo Work 是一个面向 AI Agent 的招聘平台：

- **求职者**：通过 Agent 上传简历（`import_resume`），AI 自动提取结构化数据
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

1. 首次调用工具时，自动打开浏览器 `https://hipowork.com/authorize`
2. 输入邮箱 → 获取验证码 → 输入验证码
3. 授权完成，自动返回客户端，**后续无需再操作**

> Token 30 天有效，自动刷新，无需手动配置 API Key。

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
| `import_resume` | 导入简历（Agent 解析后传入结构化数据） | candidate |

---

## 认证机制

### OAuth 2.0（推荐）

- 完整的 OAuth 授权码流程（RFC 6749）
- PKCE 支持
- Access token 30 天 + Refresh token 90 天自动轮换
- 支持 token 吊销（`POST /revoke`）

### API Key（备选）

客户端不支持 OAuth 时，可手动配置 `X-API-Key` header：

```json
{
  "mcpServers": {
    "hipo": {
      "url": "https://mcp.hipowork.com/mcp",
      "headers": {
        "X-API-Key": "fb_live_xxx"
      }
    }
  }
}
```

1. 调用 `send_verification_code` 发送验证码
2. 调用 `register_or_login` 注册（完整 API Key 只通过邮箱发送，MCP 响应只返回 Key 前缀）
3. ⚠️ API Key 30 天有效，过期后重新调用 `register_or_login`

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

```nginx
server {
    listen 80;
    server_name hipowork.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name hipowork.com;

    ssl_certificate /etc/letsencrypt/live/hipowork.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hipowork.com/privkey.pem;

    location /mcp {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }

    location = /authorize { proxy_pass http://127.0.0.1:8003; }
    location = /login     { proxy_pass http://127.0.0.1:8003; }
    location = /token     { proxy_pass http://127.0.0.1:8003; }
    location = /revoke    { proxy_pass http://127.0.0.1:8003; }
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