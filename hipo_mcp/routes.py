"""HiPo OAuth 路由：登录页 + authorize + token"""

import json
import time
import secrets
import os
import httpx
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse

BACKEND_URL = os.environ.get("HIPO_BACKEND_URL", "http://127.0.0.1:8000")
API_BASE = f"{BACKEND_URL}/api/v1"

# MCP 层限流桶：IP → [timestamp]
_send_code_bucket: dict[str, list] = {}


# ══════════════════════════════════════════
# 登录页
# ══════════════════════════════════════════

LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiPo Work 授权登录</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
       min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #fff; border-radius: 16px; padding: 40px; width: 380px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.logo { text-align: center; margin-bottom: 24px; }
.logo h1 { font-size: 24px; color: #333; }
.logo p { color: #999; font-size: 14px; margin-top: 4px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; font-size: 14px; color: #555; margin-bottom: 6px; }
.form-group input { width: 100%; padding: 12px; border: 1px solid #ddd;
                    border-radius: 8px; font-size: 15px; outline: none; }
.form-group input:focus { border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.1); }
.btn { width: 100%; padding: 13px; border: none; border-radius: 8px;
       background: #667eea; color: #fff; font-size: 16px; cursor: pointer;
       transition: background 0.3s; }
.btn:hover { background: #5a67d8; }
.error { background: #fee2e2; color: #b91c1c; padding: 10px; border-radius: 8px;
         font-size: 13px; margin-bottom: 16px; }
.success { background: #d1fae5; color: #065f46; padding: 10px; border-radius: 8px;
           font-size: 13px; margin-bottom: 16px; }
.tip { font-size: 12px; color: #999; margin-top: 16px; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>HiPo Work</h1>
    <p>授权连接到 HiPo Work MCP 服务</p>
  </div>
  {message}
  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id" value="{client_id}">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <input type="hidden" name="scope" value="{scope}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
    <input type="hidden" name="step" value="send_code">
    <div class="form-group">
      <label>邮箱</label>
      <input type="email" name="email" placeholder="you@example.com" value="{email}" required>
    </div>
    <button type="submit" class="btn">获取验证码</button>
  </form>
</div>
</body>
</html>
"""

CODE_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiPo Work 授权登录</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
       min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #fff; border-radius: 16px; padding: 40px; width: 380px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.logo { text-align: center; margin-bottom: 24px; }
.logo h1 { font-size: 24px; color: #333; }
.logo p { color: #999; font-size: 14px; margin-top: 4px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; font-size: 14px; color: #555; margin-bottom: 6px; }
.form-group input { width: 100%; padding: 12px; border: 1px solid #ddd;
                    border-radius: 8px; font-size: 15px; outline: none; }
.form-group input:focus { border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.1); }
.btn { width: 100%; padding: 13px; border: none; border-radius: 8px;
       background: #667eea; color: #fff; font-size: 16px; cursor: pointer;
       transition: background 0.3s; }
.btn:hover { background: #5a67d8; }
.tip { font-size: 12px; color: #999; margin-top: 16px; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>HiPo Work</h1>
    <p>验证码已发送至 {email}</p>
  </div>
  <form method="POST" action="/authorize">
    <input type="hidden" name="client_id" value="{client_id}">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <input type="hidden" name="scope" value="{scope}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
    <input type="hidden" name="step" value="verify">
    <input type="hidden" name="email" value="{email}">
    <div class="form-group">
      <label>输入验证码</label>
      <input type="text" name="code" placeholder="6 位验证码" maxlength="6" required>
    </div>
    <button type="submit" class="btn">完成登录</button>
  </form>
  <div class="tip">未收到？<a href="/authorize?client_id={client_id}&redirect_uri={redirect_uri_q}&state={state}">重新发送</a></div>
</div>
</body>
</html>
"""


def _login_page(**kwargs) -> HTMLResponse:
    import html as _html
    html = LOGIN_PAGE_HTML
    for k, v in kwargs.items():
        html = html.replace("{" + k + "}", str(_html.escape(str(v or ""))))
    # 清理剩余未替换的占位符
    import re
    html = re.sub(r"\{[a-z_]+\}", "", html)
    return HTMLResponse(html)


def _code_page(**kwargs) -> HTMLResponse:
    import html as _html
    import re
    html = CODE_PAGE_HTML
    for k, v in kwargs.items():
        html = html.replace("{" + k + "}", str(_html.escape(str(v or ""))))
    html = re.sub(r"\{[a-z_]+\}", "", html)
    return HTMLResponse(html)


def login_page_route(provider):
    """GET /authorize → 渲染登录页"""
    async def handler(request: Request):
        # 从 query 或 form 获取参数
        params = request.query_params if request.method == "GET" else await request.form()
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")
        scope = params.get("scope", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "S256")
        email = params.get("email", "")

        return _login_page(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            email=email,
            message="",
        )

    return handler


def authorize_route(provider):
    """处理登录表单提交（POST /authorize）：
    - step=send_code → 发送验证码，显示验证码输入页
    - step=verify → 校验验证码，生成 auth code，重定向回客户端
    """
    async def handler(request: Request):
        form = await request.form()
        client_id = form.get("client_id", "")
        redirect_uri = form.get("redirect_uri", "")
        state = form.get("state", "")
        scope = form.get("scope", "")
        code_challenge = form.get("code_challenge", "")
        code_challenge_method = form.get("code_challenge_method", "S256")
        step = form.get("step", "send_code")
        email = form.get("email", "")

        # 验证 client
        client = await provider.get_client(client_id)
        if not client:
            return JSONResponse({"error": "unauthorized_client", "error_description": "Client not registered"}, status_code=400)

        if step == "send_code":
            # MCP 层限流：防止批量轰炸验证码发送接口
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            _send_code_bucket[client_ip].append(now)
            # 清理 60s 前的记录
            _send_code_bucket[client_ip] = [t for t in _send_code_bucket[client_ip] if t > now - 60]
            if len(_send_code_bucket[client_ip]) > 5:
                return _login_page(
                    client_id=client_id, redirect_uri=redirect_uri, state=state,
                    scope=scope, code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    email=email, message="请求过于频繁，请稍后再试",
                )
            # 发送验证码到邮箱
            try:
                async with httpx.AsyncClient(timeout=10.0) as hc:
                    resp = await hc.post(f"{API_BASE}/auth/send-code", json={"email": email})
                    if resp.status_code != 200:
                        detail = resp.json().get("detail", {})
                        msg = detail.get("message", "发送失败") if isinstance(detail, dict) else str(detail)
                        return _login_page(
                            client_id=client_id, redirect_uri=redirect_uri, state=state,
                            scope=scope, code_challenge=code_challenge,
                            code_challenge_method=code_challenge_method,
                            email=email, message=f'<div class="error">{msg}</div>',
                        )
                return _code_page(
                    client_id=client_id, redirect_uri=redirect_uri, state=state,
                    scope=scope, code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    email=email, redirect_uri_q=redirect_uri,
                )
            except Exception as e:
                return _login_page(
                    client_id=client_id, redirect_uri=redirect_uri, state=state,
                    scope=scope, code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    email=email, message=f'<div class="error">发送失败：{str(e)[:80]}</div>',
                )

        if step == "verify":
            # 校验验证码并登录（role 自动推断：candidate）
            code = form.get("code", "")
            try:
                async with httpx.AsyncClient(timeout=10.0) as hc:
                    resp = await hc.post(
                        f"{API_BASE}/auth/register-or-login",
                        json={"email": email, "code": code, "role": "candidate"},
                    )
                    if resp.status_code != 200:
                        detail = resp.json().get("detail", {})
                        msg = detail.get("message", "验证失败") if isinstance(detail, dict) else str(detail)
                        return _code_page(
                            client_id=client_id, redirect_uri=redirect_uri, state=state,
                            scope=scope, code_challenge=code_challenge,
                            code_challenge_method=code_challenge_method,
                            email=email, redirect_uri_q=redirect_uri,
                            error=msg,
                        )
                    user_data = resp.json()
                    api_key = user_data.get("api_key_secret", "")
            except Exception as e:
                return _code_page(
                    client_id=client_id, redirect_uri=redirect_uri, state=state,
                    scope=scope, code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    email=email, redirect_uri_q=redirect_uri,
                    error=f"登录失败：{str(e)[:80]}",
                )

            # 登录成功 → 通过 state 预存用户信息
            from mcp.server.auth.provider import AuthorizationParams
            from urllib.parse import parse_qs, urlencode

            provider.store_pending_auth(state, {
                "user_id": user_data.get("user_id", ""),
                "role": user_data.get("role", "candidate"),
                "api_key": api_key,
            })

            # 客户端已通过 POST 提交了所有必要参数，现在直接调 authorize 生成 auth code
            # 构造完整 AuthorizationParams
            auth_params = AuthorizationParams(
                redirect_uri=redirect_uri,
                redirect_uri_provided_explicitly=True,
                scopes=scope.split() if scope else [],
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method if code_challenge_method else None,
            )

            redirect_url = await provider.authorize(client, auth_params)
            return RedirectResponse(redirect_url, status_code=302)

        return JSONResponse({"error": "invalid_request"}, status_code=400)

    return handler


def token_route(provider):
    """POST /token → 换 token"""
    async def handler(request: Request):
        form = await request.form()
        grant_type = form.get("grant_type")
        code = form.get("code")
        redirect_uri = form.get("redirect_uri")
        client_id = form.get("client_id")
        code_verifier = form.get("code_verifier")
        refresh_token = form.get("refresh_token")

        client = await provider.get_client(client_id) if client_id else None

        if grant_type == "authorization_code":
            if not code or not client:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            ac = await provider.load_authorization_code(client, code)
            if not ac:
                return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired code"}, status_code=400)
            # 授权码只能在原始 redirect_uri 上兑换，防止 code 被转发到其他回调地址。
            if not redirect_uri or str(ac.redirect_uri) != str(redirect_uri):
                return JSONResponse({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)
            # PKCE：存在 code_challenge 时必须提供并严格校验 code_verifier。
            if ac.code_challenge:
                if not code_verifier:
                    return JSONResponse({"error": "invalid_grant", "error_description": "Missing code_verifier"}, status_code=400)
                import hashlib, base64, hmac
                digest = hashlib.sha256(code_verifier.encode()).digest()
                verifier_b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                if not hmac.compare_digest(verifier_b64, ac.code_challenge):
                    return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)
            token = await provider.exchange_authorization_code(client, ac)
            return JSONResponse(token.model_dump(exclude_none=True))

        elif grant_type == "refresh_token":
            if not refresh_token or not client:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            rt = await provider.load_refresh_token(client, refresh_token)
            if not rt:
                return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired refresh token"}, status_code=400)
            scopes = (form.get("scope") or " ".join(rt.scopes)).split()
            token = await provider.exchange_refresh_token(client, rt, scopes)
            return JSONResponse(token.model_dump(exclude_none=True))

        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    return handler


def revoke_route(provider):
    """POST /revoke → 吊销 token"""
    async def handler(request: Request):
        form = await request.form()
        token = form.get("token")
        if not token:
            return JSONResponse({"error": "invalid_request", "error_description": "Missing token"}, status_code=400)
        provider.revoke_token(token)
        return JSONResponse({"ok": True})

    return handler