"""HiPo OAuth SSO 会话桥：Web 登录态 → MCP 授权服务器会话 cookie。

方案A：web 已登录时，前端用自己 bearer token 换一次性 HMAC 票据，
经同站 iframe 请求本模块 /sso；本模块向后端验票（X-MCP-Internal-Secret
双因素），成功后在本域（mcp.hipowork.com）种 HttpOnly 会话 cookie。
此后 GET /authorize 检测到有效会话 → 直接渲染"同意授权"页，免邮箱验证码。

- 票据 jti 用 STORE.setnx 一次性消费（防重放）。
- 会话本身无服务端状态：user_id/role/exp 全部编码在 cookie 的 HMAC
  签名内；签名密钥持久化到 STORE（Redis 模式下重启不丢，内存模式单进程
  足够），由授权服务器自己持有（与后端 OAUTH_SIGNING_KEY 无关）。
"""

import base64
import hashlib
import hmac
import os
import secrets
import time

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from .storage import STORE

BACKEND_URL = os.environ.get("HIPO_BACKEND_URL", "http://127.0.0.1:8000")
API_BASE = f"{BACKEND_URL}/api/v1"
MCP_INTERNAL_SECRET = os.environ.get("MCP_INTERNAL_SECRET", "")

# 会话时长：与 web 端 refresh 周期对齐（90 天），体验上"关页回来仍在登录态"
SSO_SESSION_TTL_SECONDS = 90 * 24 * 60 * 60
SSO_TICKET_TTL_SECONDS = 60  # 与后端签发端一致，兜底校验
COOKIE_NAME = "hipo_sso_session"
SSO_SIGNING_KEY_STORE = "hipo_sso_signing_key"


def _get_signing_key() -> bytes:
    """惰性生成并持久化会话签名密钥（进程级稳定，避免重启全员登出）。"""
    key = STORE.get(SSO_SIGNING_KEY_STORE)
    if not key:
        key = secrets.token_bytes(32)
        # 无 TTL 持久化；首次写入即可
        STORE.set(SSO_SIGNING_KEY_STORE, key)
    return key if isinstance(key, bytes) else bytes(key)


def _sign(msg: bytes, key: bytes) -> bytes:
    return hmac.new(key, msg, digestmod=hashlib.sha256).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _make_cookie_value(user_id: str, role: str, signing_key: bytes) -> str:
    """payload.signature；payload 内含 user_id/role/iat/exp，签名防篡改。"""
    exp = int(time.time()) + SSO_SESSION_TTL_SECONDS
    payload = f"{user_id}:{role}:{int(time.time())}:{exp}".encode()
    sig = _sign(payload, signing_key)
    return f"{_b64encode(payload)}.{_b64encode(sig)}"


def parse_cookie_value(raw: str, signing_key: bytes):
    """解析并校验会话 cookie；非法/过期返回 None。"""
    try:
        body_b64, sig_b64 = raw.split(".", 1)
        payload = _b64decode(body_b64)
        sig = _b64decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(payload, signing_key), sig):
        return None
    parts = payload.decode(errors="ignore").split(":")
    if len(parts) != 4:
        return None
    user_id, role, _iat, exp = parts
    if role not in ("candidate", "employer") or int(exp) < int(time.time()):
        return None
    return {"user_id": user_id, "role": role}


def get_sso_session(request: Request):
    """读取并校验请求携带的会话 cookie；无/非法返回 None。"""
    raw = request.cookies.get(COOKIE_NAME) or ""
    if not raw:
        return None
    return parse_cookie_value(raw, _get_signing_key())


async def sso_route(request: Request):
    """GET /sso?ticket=… → 验票（后端）→ 种会话 cookie。

    由 web 端隐藏 iframe 同站调用。票据经 HTTPS URL 传递（60s 短时效 +
    jti 一次性），跨站不涉及任何 cookie 传递。
    """
    ticket = (request.query_params.get("ticket") or "").strip()
    if not ticket or len(ticket) > 1024:
        return JSONResponse({"error": "missing_ticket"}, status_code=400)
    # 一次性消费（防重放）：同票据只允许成功一次
    if not STORE.setnx(f"sso:ticket:{ticket}", 1, ttl=SSO_TICKET_TTL_SECONDS + 30):
        return JSONResponse({"error": "ticket_reused"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{API_BASE}/auth/sso/validate",
                headers={"X-MCP-Internal-Secret": MCP_INTERNAL_SECRET},
                json={"ticket": ticket},
            )
    except Exception:
        return JSONResponse({"error": "backend_unreachable"}, status_code=502)
    if resp.status_code != 200:
        return JSONResponse({"error": "ticket_invalid"}, status_code=401)
    data = resp.json()
    user_id = str(data.get("user_id") or "")
    role = str(data.get("role") or "")
    if not user_id or role not in ("candidate", "employer"):
        return JSONResponse({"error": "ticket_invalid"}, status_code=401)

    value = _make_cookie_value(user_id, role, _get_signing_key())
    response = PlainTextResponse("ok")
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=SSO_SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


async def sso_logout_route(request: Request):
    """GET /sso/logout → 清除会话 cookie。web 登出时同站 iframe 调用。"""
    response = PlainTextResponse("ok")
    response.delete_cookie(COOKIE_NAME, path="/")
    return response