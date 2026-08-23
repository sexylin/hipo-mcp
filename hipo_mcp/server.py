"""HiPo Work MCP Server — OAuth 2.0 认证

用户流程：
1. MCP 客户端发现 OAuth 支持，自动打开浏览器到 /authorize
2. 浏览器显示登录页（邮箱+验证码）
3. 用户登录成功 → 自动重定向回客户端 → 客户端换 token
4. 后续请求自动带 Bearer token，无需手动配置 API Key
"""

import os
import json
import httpx
from fastmcp import FastMCP, Context

# ── 配置 ──
BACKEND_URL = os.environ.get("HIPO_BACKEND_URL", "http://127.0.0.1:8000")
API_BASE = f"{BACKEND_URL}/api/v1"

# ── OAuth Provider ──
from .oauth import HiPoOAuthProvider

MCP_BASE_URL = os.environ.get("HIPO_MCP_BASE_URL", "http://127.0.0.1:8003")
auth_provider = HiPoOAuthProvider(base_url=MCP_BASE_URL)

# 创建 MCP Server（带 OAuth 认证）
mcp = FastMCP(
    "HiPo Work",
    auth=auth_provider,
)


# ── 辅助：从工具上下文获取当前用户 ──

def _user(ctx: Context) -> dict:
    """从 ctx.token 获取当前用户信息"""
    try:
        if ctx.token and hasattr(ctx.token, "claims"):
            return ctx.token.claims or {}
    except Exception:
        pass
    return {}


def _require_role(ctx: Context, role: str):
    """检查角色权限，返回 None 或错误信息"""
    u = _user(ctx)
    if not u:
        return "未认证：请先通过 OAuth 登录"
    if u.get("role") != role:
        return f"权限不足：需要 {role} 角色，当前是 {u.get('role')}"
    return None


def _headers(ctx: Context) -> dict:
    """构造请求头（从 auth_provider 内存映射获取 API Key，不依赖 OAuth claims）"""
    u = _user(ctx)
    key = auth_provider.get_user_api_key(u.get("user_id", "")) if u.get("user_id") else ""
    return {"Content-Type": "application/json", "X-API-Key": key} if key else {"Content-Type": "application/json"}


def _get(ctx: Context, path: str, timeout: int = 15) -> dict:
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{API_BASE}{path}", headers=_headers(ctx))
        if resp.status_code == 401: raise ValueError("API Key 无效或已过期，请重新获取")
        if resp.status_code == 403: raise ValueError("权限不足，请确认账号角色")
        if resp.status_code == 404: raise ValueError("资源不存在")
        if resp.status_code >= 500: raise ValueError("后端服务暂时不可用，请稍后重试")
        resp.raise_for_status()
        return resp.json()


def _post(ctx: Context, path: str, body: dict = None, timeout: int = 15) -> dict:
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{API_BASE}{path}", json=body or {}, headers=_headers(ctx))
        if resp.status_code == 401: raise ValueError("API Key 无效或已过期，请重新获取")
        if resp.status_code == 403: raise ValueError("权限不足，请确认账号角色")
        if resp.status_code == 422:
            detail = resp.json().get("detail", "参数格式错误")
            raise ValueError(f"参数错误: {detail}")
        if resp.status_code == 429: raise ValueError("请求过于频繁，请稍后重试")
        if resp.status_code >= 500: raise ValueError("后端服务暂时不可用，请稍后重试")
        resp.raise_for_status()
        return resp.json()


# ══════════════════════════════════════════
# MCP Tools
# ══════════════════════════════════════════


# 公开工具（无需认证）


@mcp.tool(
    name="send_verification_code",
    description="向指定邮箱发送验证码（注册/登录前需先调用此工具）",
)
def send_verification_code(email: str) -> str:
    """发送邮箱验证码"""
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{API_BASE}/auth/send-code",
            json={"email": email},
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 429:
            detail = resp.json().get("detail", {})
            msg = detail.get("message", "请求过于频繁") if isinstance(detail, dict) else "请求过于频繁"
            return json.dumps({"error": msg}, ensure_ascii=False)
        resp.raise_for_status()
    return f"验证码已发送至 {email}"


@mcp.tool(
    name="register_or_login",
    description="使用邮箱验证码注册或登录。返回 user_id。",
)
def register_or_login(email: str, code: str, role: str = "candidate") -> str:
    """注册或登录"""
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{API_BASE}/auth/register-or-login",
            json={"email": email, "code": code, "role": role},
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 400:
            detail = resp.json().get("detail", {})
            msg = detail.get("message", "验证码错误") if isinstance(detail, dict) else "验证码错误"
            return json.dumps({"error": msg}, ensure_ascii=False)
        if resp.status_code == 401:
            detail = resp.json().get("detail", {})
            msg = detail.get("message", "验证码错误或已过期") if isinstance(detail, dict) else "验证码错误或已过期"
            return json.dumps({"error": msg}, ensure_ascii=False)
        if resp.status_code == 429:
            return json.dumps({"error": "请求过于频繁，请稍后重试"}, ensure_ascii=False)
        resp.raise_for_status()
        result = resp.json()
    return json.dumps({
        "user_id": result.get("user_id"),
        "email": result.get("email"),
        "role": result.get("role"),
        "is_new_user": result.get("is_new_user", False),
        "api_key_prefix": result.get("api_key_prefix"),
        "message": result.get("message", "注册/登录成功"),
        "注意": "完整 API Key 已发送到你的邮箱，请查收。你也可以直接在浏览器中打开 OAuth 授权页面完成登录，无需手动配置 Key。",
        "oauth_authorize_url": f"{MCP_BASE_URL}/authorize",
    }, ensure_ascii=False)


# ── 招聘方工具（employer）──


@mcp.tool(
    name="publish_job",
    description="发布招聘岗位（需要 employer 角色）。支持结构化条件 required/preferred。",
)
def publish_job(
    ctx: Context,
    title: str,
    required: list,
    preferred: dict = None,
    raw_text: str = "",
    salary_min: int = None,
    salary_max: int = None,
    salary_unit: str = "monthly",
) -> str:
    """发布岗位"""
    err = _require_role(ctx, "employer")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    result = _post(ctx, "/agent/publish-job", {
        "title": title, "raw_text": raw_text or "",
        "required": required, "preferred": preferred or {},
        "salary_min": salary_min, "salary_max": salary_max, "salary_unit": salary_unit,
    })
    return json.dumps({"job_id": result.get("job_id"), "title": result.get("title"), "location": result.get("location")}, ensure_ascii=False)


@mcp.tool(
    name="match_candidates",
    description="匹配候选人（需要 employer 角色）。返回 Top-N 结果含评分明细和工作经历/教育信息。",
)
def match_candidates(ctx: Context, required: list, preferred: dict = None, max_results: int = 10) -> str:
    """匹配候选人"""
    err = _require_role(ctx, "employer")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    result = _post(ctx, "/agent/match-candidates", {"required": required, "preferred": preferred or {}, "max_results": max_results})
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(
    name="match_job_requirement",
    description="对已发布的岗位执行自动匹配（需要 employer 角色）。直接传入 job_id。",
)
def match_job_requirement(ctx: Context, job_id: str, max_results: int = 10) -> str:
    """根据岗位 ID 自动匹配"""
    err = _require_role(ctx, "employer")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    result = _post(ctx, f"/employer/requirements/{job_id}/match", {"max_results": max_results})
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(
    name="search_candidates",
    description="自然语言搜索候选人（需要 employer 角色）。",
)
def search_candidates(ctx: Context, query: str, max_results: int = 10) -> str:
    """自然语言搜索"""
    err = _require_role(ctx, "employer")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    result = _post(ctx, "/search", {"query": query, "max_results": max_results})
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_stats",
    description="获取平台统计数据（需要 employer 角色）。",
)
def get_stats(ctx: Context) -> str:
    """平台统计"""
    err = _require_role(ctx, "employer")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    result = _get(ctx, "/agent/stats")
    return json.dumps(result, ensure_ascii=False)


@mcp.tool(
    name="market_analysis",
    description="市场分析：查询某技能/行业的人才供需情况（需要 employer 角色）。",
)
def market_analysis(ctx: Context, keyword: str = None, industry: str = None, location: str = None) -> str:
    """市场分析"""
    err = _require_role(ctx, "employer")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    body = {}
    if keyword: body["keyword"] = keyword
    if industry: body["industry"] = industry
    if location: body["location"] = location
    result = _post(ctx, "/agent/market-analysis", body)
    return json.dumps(result, ensure_ascii=False)


# ── 求职者工具（candidate）──


@mcp.tool(
    name="import_resume",
    description="导入简历（需要 candidate 角色）。Agent 自行用 LLM 解析简历文本为结构化数据后传入。",
)
def import_resume(
    ctx: Context,
    basic_info: dict,
    work_experiences: list = None,
    education: list = None,
    skills: list = None,
    certificates: list = None,
    languages: list = None,
) -> str:
    """导入简历"""
    err = _require_role(ctx, "candidate")
    if err: return json.dumps({"error": err}, ensure_ascii=False)
    result = _post(ctx, "/agent/import-resume", {
        "basic_info": basic_info,
        "work_experiences": work_experiences or [],
        "education": education or [],
        "skills": skills or [],
        "certificates": certificates or [],
        "languages": languages or [],
    })
    return json.dumps(result, ensure_ascii=False)


# ══════════════════════════════════════════
# HTTP 入口
# ══════════════════════════════════════════

app = mcp.http_app()


def main():
    """stdio 模式入口"""
    mcp.run()


if __name__ == "__main__":
    main()