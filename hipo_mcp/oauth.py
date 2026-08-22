"""HiPo Work OAuth Provider — 完整 OAuth 授权服务器

用户流程：
1. MCP 客户端发现 OAuth 支持 → 打开浏览器到 /authorize
2. 显示登录页（邮箱+验证码）
3. 用户验证成功后 → 生成 auth code → 重定向回客户端
4. 客户端用 code 换 access_token + refresh_token
5. 后续请求自动带 Bearer token
"""

import os
import json
import time
import secrets
import httpx
from typing import Optional

from fastmcp.server.auth import OAuthProvider, AccessToken
from mcp.server.auth.provider import (
    AuthorizationCode, RefreshToken, OAuthToken,
    AuthorizationParams, OAuthClientInformationFull,
    AuthorizeError, TokenError,
)

# ── 配置 ──
BACKEND_URL = os.environ.get("HIPO_BACKEND_URL", "http://127.0.0.1:8000")
API_BASE = f"{BACKEND_URL}/api/v1"

# Token 有效期
ACCESS_TOKEN_EXPIRY = 3600 * 24 * 30      # 30 天
AUTH_CODE_EXPIRY = 300                     # 5 分钟
REFRESH_TOKEN_EXPIRY = 3600 * 24 * 90     # 90 天


class HiPoOAuthProvider(OAuthProvider):
    """OAuth 授权提供者：对接 HiPo 邮箱验证码登录"""

    def __init__(self, base_url: str):
        super().__init__(base_url=base_url)
        # 内存存储
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self._access_to_refresh: dict[str, str] = {}
        self._refresh_to_access: dict[str, str] = {}
        # 预授权会话：state → {user_id, role, api_key}
        self._pending_auth: dict[str, dict] = {}

    def store_pending_auth(self, state: str, user_info: dict):
        """存储 OAuth 流程中已验证的用户信息（登录页 → authorize 传递）"""
        self._pending_auth[state] = user_info

    def get_pending_auth(self, state: str) -> dict:
        """取出并消费预授权信息"""
        return self._pending_auth.pop(state, {})

    # ══════════════════════════════════════════
    # 客户端注册
    # ══════════════════════════════════════════

    def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        return self.clients.get(client_id)

    def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients[client_info.client_id] = client_info

    # ══════════════════════════════════════════
    # 授权码生成
    # ══════════════════════════════════════════

    def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """生成授权码并返回重定向 URI。从 _pending_auth 获取用户信息。"""
        from mcp.server.auth.handlers.authorize import construct_redirect_uri

        if client.client_id not in self.clients:
            raise AuthorizeError("unauthorized_client", f"Client '{client.client_id}' not registered")

        # 通过 state 获取用户信息
        user_info = self.get_pending_auth(params.state or "")
        user_id = user_info.get("user_id", "")
        role = user_info.get("role", "candidate")
        api_key = user_info.get("api_key", "")
        if not user_id:
            raise AuthorizeError("access_denied", "User not authenticated")

        code_value = f"hipo_ac_{secrets.token_hex(24)}"
        expires_at = time.time() + AUTH_CODE_EXPIRY

        scopes_list = params.scopes or []
        if client.scope:
            allowed = set(client.scope.split())
            scopes_list = [s for s in scopes_list if s in allowed]

        self.auth_codes[code_value] = AuthorizationCode(
            code=code_value,
            client_id=client.client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=scopes_list,
            expires_at=expires_at,
            code_challenge=params.code_challenge,
            subject=json.dumps({"user_id": user_id, "role": role, "api_key": api_key}),
        )

        return construct_redirect_uri(
            str(params.redirect_uri), code=code_value, state=params.state
        )

    # ══════════════════════════════════════════
    # 授权码验证 + 换 token
    # ══════════════════════════════════════════

    async def load_authorization_code(self, client: OAuthClientInformationFull, code: str) -> Optional[AuthorizationCode]:
        ac = self.auth_codes.get(code)
        if not ac: return None
        if ac.client_id != client.client_id: return None
        if ac.expires_at < time.time():
            self.auth_codes.pop(code, None)
            return None
        return ac

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, ac: AuthorizationCode) -> OAuthToken:
        if ac.code not in self.auth_codes:
            raise TokenError("invalid_grant", "Authorization code not found or already used")
        self.auth_codes.pop(ac.code, None)

        subject = getattr(ac, "subject", None) or ""
        try: user_meta = json.loads(subject) if subject else {}
        except: user_meta = {}
        user_id = user_meta.get("user_id", "unknown")
        role = user_meta.get("role", "candidate")
        api_key = user_meta.get("api_key", "")

        access_token_value = f"hipo_at_{secrets.token_hex(32)}"
        refresh_token_value = f"hipo_rt_{secrets.token_hex(32)}"
        now = int(time.time())

        self.access_tokens[access_token_value] = AccessToken(
            token=access_token_value, client_id=client.client_id,
            scopes=ac.scopes, expires_at=now + ACCESS_TOKEN_EXPIRY,
            claims={"user_id": user_id, "role": role, "api_key": api_key},
        )
        self.refresh_tokens[refresh_token_value] = RefreshToken(
            token=refresh_token_value, client_id=client.client_id,
            scopes=ac.scopes, expires_at=now + REFRESH_TOKEN_EXPIRY,
        )
        self._access_to_refresh[access_token_value] = refresh_token_value
        self._refresh_to_access[refresh_token_value] = access_token_value

        return OAuthToken(
            access_token=access_token_value, token_type="Bearer",
            expires_in=ACCESS_TOKEN_EXPIRY, refresh_token=refresh_token_value,
            scope=" ".join(ac.scopes),
        )

    # ══════════════════════════════════════════
    # Token 验证与刷新
    # ══════════════════════════════════════════

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        at = self.access_tokens.get(token)
        if not at: return None
        if at.expires_at is not None and at.expires_at < time.time():
            self._revoke_pair(access_token_str=token)
            return None
        return at

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        return await self.verify_token(token)

    async def load_refresh_token(self, client: OAuthClientInformationFull, token: str) -> Optional[RefreshToken]:
        rt = self.refresh_tokens.get(token)
        if not rt: return None
        if rt.client_id != client.client_id: return None
        if rt.expires_at is not None and rt.expires_at < time.time():
            self._revoke_pair(refresh_token_str=token)
            return None
        return rt

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, rt: RefreshToken, scopes: list) -> OAuthToken:
        original = set(rt.scopes)
        requested = set(scopes)
        if not requested.issubset(original):
            raise TokenError("invalid_scope", "Requested scopes exceed authorized scopes")
        self._revoke_pair(refresh_token_str=rt.token)

        access_token_value = f"hipo_at_{secrets.token_hex(32)}"
        refresh_token_value = f"hipo_rt_{secrets.token_hex(32)}"
        now = int(time.time())

        access_token_str = self._refresh_to_access.get(rt.token)
        old_at = self.access_tokens.get(access_token_str) if access_token_str else None
        claims = getattr(old_at, "claims", {}) or {}

        self.access_tokens[access_token_value] = AccessToken(
            token=access_token_value, client_id=client.client_id,
            scopes=scopes, expires_at=now + ACCESS_TOKEN_EXPIRY, claims=claims,
        )
        self.refresh_tokens[refresh_token_value] = RefreshToken(
            token=refresh_token_value, client_id=client.client_id,
            scopes=scopes, expires_at=now + REFRESH_TOKEN_EXPIRY,
        )
        self._access_to_refresh[access_token_value] = refresh_token_value
        self._refresh_to_access[refresh_token_value] = access_token_value

        return OAuthToken(
            access_token=access_token_value, token_type="Bearer",
            expires_in=ACCESS_TOKEN_EXPIRY, refresh_token=refresh_token_value,
            scope=" ".join(scopes),
        )

    def revoke_token(self, token) -> None:
        self._revoke_pair(access_token_str=token.token if hasattr(token, "token") else str(token))

    # ══════════════════════════════════════════
    # 路由
    # ══════════════════════════════════════════

    def get_routes(self, mcp_path: str = None) -> list:
        from starlette.routing import Route
        from .routes import authorize_route, token_route, login_page_route
        return [
            Route("/authorize", endpoint=authorize_route(self), methods=["GET", "POST"]),
            Route("/login", endpoint=login_page_route(self), methods=["GET", "POST"]),
            Route("/token", endpoint=token_route(self), methods=["POST"]),
        ]

    # ══════════════════════════════════════════
    # 内部
    # ══════════════════════════════════════════

    def _revoke_pair(self, access_token_str: str = None, refresh_token_str: str = None):
        if access_token_str:
            rt = self._access_to_refresh.pop(access_token_str, None)
            self.access_tokens.pop(access_token_str, None)
            if rt:
                self.refresh_tokens.pop(rt, None)
                self._refresh_to_access.pop(rt, None)
        if refresh_token_str:
            at = self._refresh_to_access.pop(refresh_token_str, None)
            self.refresh_tokens.pop(refresh_token_str, None)
            if at:
                self.access_tokens.pop(at, None)
                self._access_to_refresh.pop(at, None)