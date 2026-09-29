"""对照实验：直接调用 _refresh_backend_token，区分「后端不可达」与「后端拒绝」。

我们把异常 str(exc) 空的那行日志是关键线索：`backend refresh unreachable:` 后面是空的。
本脚本直接跑同一条调用，打印异常的类型、repr、str，以确定：
  - 连不上 → httpx.ConnectError/Timeout（通常 str 为空）
  - 连上了但被 401/500 → 不会走到 unreachable 分支

用法（在 hipo-mcp 目录）：
    HIPO_BACKEND_URL=http://127.0.0.1:8000 .venv/bin/python diagnose_refresh.py
    HIPO_BACKEND_URL=http://<服务器内网地址>:8000 .venv/bin/python diagnose_refresh.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hipo_mcp.oauth import API_BASE, BACKEND_URL, MCP_INTERNAL_SECRET, HiPoOAuthProvider  # noqa: E402


async def main() -> int:
    print(f"BACKEND_URL = {BACKEND_URL}")
    print(f"API_BASE    = {API_BASE}")
    print(f"MCP_INTERNAL_SECRET 已配置: {'是' if MCP_INTERNAL_SECRET else '❌ 否（会导致握手失败）'}")
    print()

    # 先做最简单的连通性检查
    import httpx

    url = f"{API_BASE}/auth/oauth/refresh"
    print(f"POST {url}")
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.post(
                url,
                headers={"X-MCP-Internal-Secret": MCP_INTERNAL_SECRET or "dummy"},
                json={"refresh_token": "invalid-for-diagnosis", "client_id": "diag"},
            )
        print(f"  连通: HTTP {resp.status_code}")
        print(f"  body: {resp.text[:300]}")
        if resp.status_code == 401 and "INVALID_INTERNAL_CLIENT" in resp.text:
            print("  ⚠️ 密钥不匹配：后端与 MCP 的 MCP_INTERNAL_SECRET 不一致")
        elif resp.status_code == 401 and "OAUTH_REFRESH_INVALID" in resp.text:
            print("  ✅ 密钥正确！401 只是诊断用的无效 token，链路本身是通的")
        elif resp.status_code == 422:
            print("  ✅ 密钥正确！422 是参数校验（诊断参数不全），链路通")
    except Exception as exc:
        print(f"  ❌ 连接失败：{type(exc).__name__}")
        print(f"     str(exc) = {str(exc)!r}   <- 这正是服务器日志里那行空值的来源")
        print(f"     repr     = {repr(exc)}")
        return 1

    print("\n--- 现在直接跑 _refresh_backend_token（复现服务器那条日志）---")
    provider = HiPoOAuthProvider(base_url="http://127.0.0.1:8003")
    try:
        await provider._refresh_backend_token("invalid-for-diagnosis", "diag")
        print("  意外：调用成功了？")
    except Exception as exc:
        from mcp.server.auth.provider import TokenError

        print(f"  异常类型: {type(exc).__name__}")
        print(f"  str = {str(exc)!r}   <- 若为空，就是服务器日志'后为空'的原因")
        print(f"  repr = {repr(exc)[:300]}")
        if isinstance(exc, TokenError):
            print(f"  TokenError.error = {exc.error!r}  (合法值? {exc.error in {'invalid_request','invalid_client','invalid_grant','unauthorized_client','unsupported_grant_type','invalid_scope'}})")
            print(f"  TokenError.error_description = {exc.error_description!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
