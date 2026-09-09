# HiPo Work MCP Server

<div align="center">

# 让你的简历，被 AI 看到
### 让机会与人才自然相遇

[![MCP Server](https://img.shields.io/badge/MCP-Server-blue)](https://modelcontextprotocol.io)
[![OAuth 2.0](https://img.shields.io/badge/Auth-OAuth2.0-green)](https://oauth.net/2/)
[![Registry](https://img.shields.io/badge/MCP%20Registry-io.github.sexylin%2Fhipo--work-orange)](https://registry.modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**官网：** [https://hipowork.com](https://hipowork.com) · [https://www.hipowork.com](https://www.hipowork.com)  
**远程 MCP 端点：** `https://mcp.hipowork.com/mcp`

</div>

---

## 🌟 平台理念

在传统的招聘求职中，优秀的简历常常沉睡在静态文档或封闭的简历库中，被动等待关键词匹配。

**HiPo Work** 致力于改变这一现状：
- **把简历沉淀为高精度语义资产**：通过 AI Agent 或平台解析，求职者的专业技能、独立项目、商业落地与工作成果被全量结构化并转化为语义向量。
- **让你的简历被 AI 工具随时检索**：不管是 Claude Code、Cursor、OpenAI CodeX、Hermes Agent 还是各类企业自建招聘 Agent，都能在秒级通过 MCP 工具精准检索、评估与连接候选人。
- **让机会与人才自然相遇**：不再需要海投或盲目筛选，由 Agent 充当智能助理，基于真实能力与项目深度实现招聘方与求职者的双向精准触达。

---

## 🔗 相关生态与公开仓库

HiPo Work 提供了完整的 Agent 原生招聘生态，涵盖 MCP 协议服务、客户端命令行工具等：

| 项目 / 平台 | 链接 | 说明 |
|------------|------|------|
| **官方网站** | [hipowork.com](https://hipowork.com) | 包含求职者中心、招聘方控制台、岗位发布与语义匹配演示 |
| **hipo-mcp**（本项目） | [github.com/sexylin/hipo-mcp](https://github.com/sexylin/hipo-mcp) | 远程 MCP 服务端，遵循 Model Context Protocol 标准，支持 OAuth 2.0 |
| **hipowork-cli** | [github.com/sexylin/hipowork-cli](https://github.com/sexylin/hipowork-cli) | 客户端命令行工具集（PyPI: `pip install hipowork-cli`），提供 `hipo` / `hipowork-cli` 终端命令 |
| **MCP Registry** | `io.github.sexylin/hipo-work` | MCP 官方 Registry 认证注册服务坐标 |

---

## 🚀 快速接入（主流 Agent 矩阵）

远程 MCP 接入端点统一为：`https://mcp.hipowork.com/mcp`

### 1. 客户端配置

#### Claude Code CLI
```bash
claude mcp add hipo https://mcp.hipowork.com/mcp
```

#### Claude Desktop
在 `claude_desktop_config.json` 中配置：
```json
{
  "mcpServers": {
    "hipo": {
      "url": "https://mcp.hipowork.com/mcp"
    }
  }
}
```

#### Cursor / VS Code
在 MCP 配置面板（SSE / HTTP 方式）添加：
```
https://mcp.hipowork.com/mcp
```

#### OpenAI CodeX
在 `~/.codex/config.toml` 中配置：
```toml
[mcp_servers.hipo]
url = "https://mcp.hipowork.com/mcp"
```

#### Hermes Agent
在 `~/.hermes/config.yaml` 中配置：
```yaml
mcp_servers:
  hipo:
    url: "https://mcp.hipowork.com/mcp"
```

#### WorkBuddy
控制台进入【扩展与设置】→【MCP 服务器】，添加自定义 HTTP 远程服务：
```
URL: https://mcp.hipowork.com/mcp
```

---

### 2. 两阶段唤起与认证机制

HiPo Work 采用安全的 **OAuth 2.0 授权码流程（PKCE S256）**，无需手动管理长久硬编码密钥：

1. **配置服务**：按照上述步骤配置各客户端。
2. **唤起认证与使用**：
   - 当你在 Agent 对话框中发出指令（例如*“帮我匹配适合我的岗位”*或*“帮我搜索区块链开发工程师”*）时，Agent 首次调用工具会收到 401 提示；
   - 客户端终端或界面会输出授权 URL 并自动打开浏览器（`https://mcp.hipowork.com/authorize`）；
   - 输入邮箱并验证（若在官网 [hipowork.com](https://hipowork.com) 已登录，则直接显示**「确认授权」**一键放行）；
   - 授权完成后 Token 自动安全持久化，Agent 无缝继续执行任务。

---

## 🛠️ MCP 工具全集

### 求职者（Candidate）工具

| 工具名 | 说明 |
|--------|------|
| `import_resume` | **核心**：导入或更新求职者简历。由 Agent 本地解析结构化数据后传入，包含基础信息、工作经历、**独立项目经历（projects）**、教育背景、技能栈等，支持同时附带简历文件 Base64 存档 |
| `upload_resume_attachment` | 单独为当前求职者上传或补交原始简历附件（PDF、DOCX、图片等 Base64 编码） |
| `match_jobs_for_me` | 根据当前简历智能匹配所有在招岗位，返回按匹配度降序排列的岗位列表及评分明细（行业、技能年限、经历） |

### 招聘方（Employer）工具

| 工具名 | 说明 |
|--------|------|
| `create_company` | 创建公司信息（输入公司名、公司简介，可指定是否设为默认企业） |
| `set_default_company` | 将指定企业主体设为默认公司 |
| `list_companies` | 查询当前招聘方名下的所有企业主体列表及默认企业 |
| `publish_job` | 发布招聘需求，支持技能要求、经验年限、地点、薪资（支持 `salary_currency`: CNY/USDT/USD/EUR/GBP/AUD/SGD）等结构化条件 |
| `close_job` | 关闭已发布的招聘需求，停止候选人匹配与投递 |
| `match_candidates` | 根据自定义条件（required/preferred）匹配全平台公开候选人，输出多维度评分 |
| `match_job_requirement` | 传入已发布的 `job_id`，自动触发多维度语义与硬性匹配 |
| `search_candidates` | 使用自然语言（如*“成都 5年经验 熟悉Solidity和Go的全栈”*）直接检索人才库 |
| `market_analysis` | 查询特定技术栈、行业或城市的人才供需热度、平均经验分布及市场洞察 |
| `get_stats` | 获取平台在招岗位总数、人才库活跃分布等全景统计 |

### 开放 / 认证工具

| 工具名 | 说明 |
|--------|------|
| `send_verification_code` | 向指定邮箱发送登录/注册验证码 |
| `register_or_login` | 提交验证码完成注册或登录 |

---

## 💡 典型 Agent 对话范式（开箱即用 Prompt）

### 求职者示例：让 Agent 解析本地简历并导入平台
> “请读取我本地的简历 `/path/to/my_resume.pdf`，提取我的工作经历、独立项目经历、技能与教育背景，调用 HiPo Work 的 `import_resume` 工具导入到平台，并附带上传原始附件。导入成功后帮我查询最匹配的岗位。”

### 招聘方示例：发布岗位并自动寻找匹配人才
> “帮我发布一个在成都的 Senior Python 后端研发岗位，要求3年以上经验，熟悉 FastAPI 与 PostgreSQL，月薪 20k-35k（币种支持 CNY/USDT/USD/EUR/GBP/AUD/SGD）。发布后立即执行自动匹配，列出前 3 位最合适的候选人并分析匹配优势。”

---

## 📄 License

本项目基于 [MIT License](LICENSE) 开源。
