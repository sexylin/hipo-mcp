# HiPo Work MCP Server

将 HiPo Work 招聘平台工具暴露为 MCP (Model Context Protocol) 工具，供 AI Agent (Claude Desktop、Hermes Agent、Cursor 等支持 MCP 的客户端) 调用。

## 功能工具

| 工具名 | 说明 | 认证要求 |
|--------|------|----------|
| `send_verification_code` | 发送邮箱验证码 | 公开 |
| `register_or_login` | 注册/登录，获取 API Key | 公开 |
| `publish_job` | 发布招聘岗位（结构化条件） | employer |
| `match_candidates` | 匹配候选人（含评分明细+工作经历） | employer |
| `match_job_requirement` | 按已发布岗位 ID 自动匹配候选人 | employer |
| `search_candidates` | 自然语言搜索候选人 | employer |
| `get_stats` | 平台统计数据 | employer |
| `market_analysis` | 市场分析 | employer |
| `import_resume` | 导入简历（Agent 解析后传入结构化数据） | candidate |

## 快速开始（本地测试）

```bash
# 安装
pip install hipo-mcp

# 启动（stdio 模式，仅供本地测试）
hipo-mcp
```

## 生产部署（云端 HTTP）

### 1. 安装依赖

```bash
pip install fastmcp httpx uvicorn
```

### 2. 启动服务

```bash
uvicorn hipo_mcp.server:app --host 127.0.0.1 --port 8003
```

### 3. Nginx 反代（必须配 HTTPS）

```nginx
# 强制 HTTPS
server {
    listen 80;
    server_name hypework.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name hypework.com;

    # SSL 证书（用 certbot 或云厂商签发）
    ssl_certificate /etc/ssl/certs/hypework.com.pem;
    ssl_certificate_key /etc/ssl/private/hypework.com.key;

    location /mcp {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

> **⚠️ 安全要求：** MCP 通信包含 API Key，必须使用 HTTPS。
> 未配置 HTTPS 之前，API Key 会在网络上明文传输。

### 4. MCP 客户端配置

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "hipo": {
      "url": "https://hypework.com/mcp",
      "headers": {
        "X-API-Key": "fb_live_xxxxx"
      }
    }
  }
}
```

**Hermes Agent** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  hipo:
    url: "https://hypework.com/mcp"
    headers:
      X-API-Key: "fb_live_xxxxx"
```

## 获取 API Key

1. 调用 `send_verification_code` 工具（传入邮箱）
2. 调用 `register_or_login` 工具（传入邮箱 + 验证码 + 角色）
3. **完整 API Key 已发送到该邮箱**，请查收邮件
4. 将 API Key 配置到 MCP 客户端的 `X-API-Key` header

⚠️ API Key 24 小时过期，过期后需重新注册获取。

## 认证机制

**每个用户独立 API Key**（通过 `X-API-Key` header 传入），按角色控制权限：

- 公开工具：`send_verification_code`、`register_or_login`
- employer 工具：`publish_job`、`match_candidates`、`search_candidates`、`get_stats`、`market_analysis`、`match_job_requirement`
- candidate 工具：`import_resume`
- 角色不符返回 `{"error": "权限不足：需要 X 角色"}`

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `HIPO_BACKEND_URL` | 否 | 后端地址，默认 `http://127.0.0.1:8000` |

## 开发

```bash
pip install -e .
uvicorn hipo_mcp.server:app --host 0.0.0.0 --port 8003 --reload
```