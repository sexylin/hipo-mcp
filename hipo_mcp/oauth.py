"""HiPo Work OAuth Provider.

HiPo Work is the authorization server for its MCP clients. After the user
finishes the email login page, the MCP authorization code is exchanged for a
HiPo Work OAuth token.
"""

import json
import os
import secrets
import time
from typing import Optional

import httpx
from fastmcp.server.auth import AccessToken, OAuthProvider
from fastmcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthClientInformationFull,
    OAuthToken,
    RegistrationError,
    RefreshToken,
    TokenError,
)

BACKEND_URL = os.environ.get("HIPO_BACKEND_URL", "http://127.0.0.1:8000")
API_BASE = f"{BACKEND_URL}/api/v1"
MCP_INTERNAL_SECRET = os.environ.get("MCP_INTERNAL_SECRET", "")

ACCESS_TOKEN_EXPIRY = 15 * 60
AUTH_CODE_EXPIRY = 5 * 60
REFRESH_TOKEN_EXPIRY = 90 * 24 * 60 * 60

# These values intentionally mirror Backend's role/scope contract.
ROLE_SCOPES = {
    "candidate": {"profile", "candidate:read", "candidate:write"},
    "employer": {"profile", "employer:read", "employer:write"},
}


class HiPoOAuthProvider(OAuthProvider):
    """OAuth provider backed by HiPo Work's own user accounts."""

    def __init__(self, base_url: str, **kwargs):
        super().__init__(base_url=base_url, **kwargs)
        # Phase 1 keeps protocol state in memory. Phase 2 moves this state to
        # Redis/PostgreSQL before horizontal scaling.
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self._access_to_refresh: dict[str, str] = {}
        self._refresh_to_access: dict[str, str] = {}
        self._pending_auth: dict[str, dict] = {}

    def store_pending_transaction(self, state: str, transaction: dict) -> None:
        """Store the browser transaction that must survive the login form."""
        if not state:
            return
        self._pending_auth[state] = {
            "_ts": time.time(),
            "transaction": dict(transaction),
        }

    def store_pending_auth(self, state: str, user_info: dict) -> None:
        pending = self._pending_auth.get(state)
        if not pending or pending.get("_ts", 0) + AUTH_CODE_EXPIRY < time.time():
            return
        pending.update(user_info)
        pending["_ts"] = time.time()

    def get_pending_auth(self, state: str) -> dict:
        info = self._pending_auth.pop(state, {})
        if info and info.get("_ts", 0) + AUTH_CODE_EXPIRY < time.time():
            return {}
        return info

    def get_pending_transaction(self, state: str) -> dict:
        """Read the login transaction without consuming it."""
        info = self._pending_auth.get(state, {})
        if not info or info.get("_ts", 0) + AUTH_CODE_EXPIRY < time.time():
            self._pending_auth.pop(state, None)
            return {}
        return dict(info.get("transaction", {}))

    def update_pending_transaction(self, state: str, **values: str) -> bool:
        """Add browser-login fields to an existing, unexpired transaction."""
        info = self._pending_auth.get(state, {})
        if not info or info.get("_ts", 0) + AUTH_CODE_EXPIRY < time.time():
            self._pending_auth.pop(state, None)
            return False
        info["transaction"].update(values)
        info["_ts"] = time.time()
        return True

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.token_endpoint_auth_method != "none":
            raise RegistrationError(
                "invalid_client_metadata",
                "Only public PKCE clients with token_endpoint_auth_method=none are supported",
            )
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        from mcp.server.auth.handlers.authorize import construct_redirect_uri

        if client.client_id not in self.clients:
            raise AuthorizeError("unauthorized_client", "Client is not registered")
        if client.redirect_uris and params.redirect_uri not in client.redirect_uris:
            raise AuthorizeError("invalid_request", "redirect_uri is not registered")

        user_info = self.get_pending_auth(params.state or "")
        transaction = user_info.get("transaction", {})
        if (
            not transaction
            or transaction.get("client_id") != client.client_id
            or transaction.get("redirect_uri") != str(params.redirect_uri)
            or transaction.get("code_challenge") != params.code_challenge
            or transaction.get("code_challenge_method") != "S256"
            or transaction.get("resource", "") != (params.resource or "")
        ):
            raise AuthorizeError("invalid_request", "Authorization transaction mismatch")
        user_id = user_info.get("user_id", "")
        role = user_info.get("role", "")
        if not user_id or role not in ("candidate", "employer"):
            raise AuthorizeError("access_denied", "User is not authenticated")

        scopes = list(params.scopes or user_info.get("scopes") or ["profile"])
        allowed_role_scopes = ROLE_SCOPES[role]
        if not set(scopes).issubset(allowed_role_scopes):
            raise AuthorizeError("invalid_scope", "Requested scopes are not valid for this role")
        if client.scope and not set(scopes).issubset(set(client.scope.split())):
            raise AuthorizeError("invalid_scope", "Requested scope was not registered for this client")

        code_value = f"hipo_ac_{secrets.token_urlsafe(32)}"
        self.auth_codes[code_value] = AuthorizationCode(
            code=code_value,
            client_id=client.client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=scopes,
            expires_at=int(time.time()) + AUTH_CODE_EXPIRY,
            code_challenge=params.code_challenge,
            resource=params.resource,
            subject=json.dumps({"user_id": user_id, "role": role}),
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code_value, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, code: str
    ) -> Optional[AuthorizationCode]:
        auth_code = self.auth_codes.get(code)
        if not auth_code or auth_code.client_id != client.client_id:
            return None
        if auth_code.expires_at < int(time.time()):
            self.auth_codes.pop(code, None)
            return None
        return auth_code

    async def _exchange_backend_identity(
        self, user_id: str, client_id: str, role: str, scopes: list[str]
    ) -> dict:
        if not MCP_INTERNAL_SECRET:
            raise TokenError("invalid_grant", "HiPo OAuth internal secret is not configured")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{API_BASE}/auth/oauth/exchange",
                    headers={"X-MCP-Internal-Secret": MCP_INTERNAL_SECRET},
                    json={
                        "user_id": user_id,
                        "client_id": client_id,
                        "role": role,
                        "scopes": scopes,
                    },
                )
            if response.status_code != 200:
                raise TokenError("server_error", "HiPo OAuth token exchange failed")
            result = response.json()
            if not result.get("access_token") or not result.get("refresh_token"):
                raise TokenError("server_error", "HiPo OAuth token exchange returned no tokens")
            return result
        except TokenError:
            raise
        except Exception as exc:
            raise TokenError("temporarily_unavailable", "HiPo OAuth backend is unavailable") from exc

    async def _refresh_backend_token(self, refresh_token: str, client_id: str) -> dict:
        if not MCP_INTERNAL_SECRET:
            raise TokenError("invalid_grant", "HiPo OAuth internal secret is not configured")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{API_BASE}/auth/oauth/refresh",
                    headers={"X-MCP-Internal-Secret": MCP_INTERNAL_SECRET},
                    json={"refresh_token": refresh_token, "client_id": client_id},
                )
            if response.status_code != 200:
                raise TokenError("invalid_grant", "HiPo OAuth refresh token is invalid")
            result = response.json()
            if not result.get("access_token") or not result.get("refresh_token"):
                raise TokenError("server_error", "HiPo OAuth refresh returned no tokens")
            return result
        except TokenError:
            raise
        except Exception as exc:
            raise TokenError("temporarily_unavailable", "HiPo OAuth backend is unavailable") from exc

    @staticmethod
    def _subject(auth_code: AuthorizationCode) -> tuple[str, str]:
        try:
            data = json.loads(getattr(auth_code, "subject", "") or "")
        except (TypeError, ValueError):
            data = {}
        return str(data.get("user_id", "")), str(data.get("role", ""))

    def _store_token_pair(
        self,
        client_id: str,
        scopes: list[str],
        role: str,
        user_id: str,
        token_data: dict,
    ) -> OAuthToken:
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = int(token_data.get("expires_in", ACCESS_TOKEN_EXPIRY))
        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + expires_in,
            claims={"user_id": user_id, "role": role},
        )
        self.refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + REFRESH_TOKEN_EXPIRY,
        )
        self._access_to_refresh[access_token] = refresh_token
        self._refresh_to_access[refresh_token] = access_token
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, auth_code: AuthorizationCode
    ) -> OAuthToken:
        if auth_code.code not in self.auth_codes:
            raise TokenError("invalid_grant", "Authorization code was already used")
        self.auth_codes.pop(auth_code.code, None)
        user_id, role = self._subject(auth_code)
        if not user_id or role not in ("candidate", "employer"):
            raise TokenError("invalid_grant", "Authorization code has invalid identity")
        token_data = await self._exchange_backend_identity(
            user_id, client.client_id, role, list(auth_code.scopes)
        )
        return self._store_token_pair(
            client.client_id, list(auth_code.scopes), role, user_id, token_data
        )

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        access_token = self.access_tokens.get(token)
        if not access_token:
            return None
        if access_token.expires_at is not None and access_token.expires_at < int(time.time()):
            self._revoke_pair(access_token_str=token)
            return None
        return access_token

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        return await self.verify_token(token)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, token: str
    ) -> Optional[RefreshToken]:
        refresh_token = self.refresh_tokens.get(token)
        if not refresh_token or refresh_token.client_id != client.client_id:
            return None
        if refresh_token.expires_at is not None and refresh_token.expires_at < int(time.time()):
            self._revoke_pair(refresh_token_str=token)
            return None
        return refresh_token

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list
    ) -> OAuthToken:
        original_scopes = set(refresh_token.scopes)
        requested_scopes = set(scopes)
        if not requested_scopes.issubset(original_scopes):
            raise TokenError("invalid_scope", "Requested scopes exceed authorized scopes")

        old_access_value = self._refresh_to_access.get(refresh_token.token)
        old_access = self.access_tokens.get(old_access_value) if old_access_value else None
        claims = dict(getattr(old_access, "claims", {}) or {})
        role = str(claims.get("role", ""))
        user_id = str(claims.get("user_id", ""))
        token_data = await self._refresh_backend_token(refresh_token.token, client.client_id)
        self._revoke_pair(refresh_token_str=refresh_token.token)
        return self._store_token_pair(
            client.client_id, list(scopes), role, user_id, token_data
        )

    async def revoke_token(self, token) -> None:
        token_value = token.token if hasattr(token, "token") else str(token)
        if token_value in self.access_tokens:
            self._revoke_pair(access_token_str=token_value)
        elif token_value in self.refresh_tokens:
            self._revoke_pair(refresh_token_str=token_value)

    def get_routes(self, mcp_path: str = None) -> list:
        from starlette.routing import Route
        from mcp.server.auth.json_response import PydanticJSONResponse
        from mcp.server.auth.routes import build_metadata, cors_middleware
        from .routes import authorize_route, login_page_route

        standard_routes = super().get_routes(mcp_path)
        routes = [
            route
            for route in standard_routes
            if getattr(route, "path", "") != "/authorize"
        ]
        # FastMCP's default metadata advertises confidential-client methods.  This
        # provider is OAuth-only and only accepts public PKCE clients.
        metadata = build_metadata(
            self.base_url,
            self.service_documentation_url,
            self.client_registration_options or ClientRegistrationOptions(),
            self.revocation_options or RevocationOptions(),
        )
        metadata.token_endpoint_auth_methods_supported = ["none"]
        metadata.revocation_endpoint_auth_methods_supported = ["none"]

        async def metadata_endpoint(request):
            return PydanticJSONResponse(
                content=metadata,
                headers={"Cache-Control": "public, max-age=300"},
            )

        for index, route in enumerate(routes):
            if getattr(route, "path", "") == "/.well-known/oauth-authorization-server":
                routes[index] = Route(
                    route.path,
                    endpoint=cors_middleware(metadata_endpoint, ["GET", "OPTIONS"]),
                    methods=route.methods,
                )
        routes.extend(
            [
                Route("/authorize", endpoint=login_page_route(self), methods=["GET"]),
                Route("/authorize", endpoint=authorize_route(self), methods=["POST"]),
            ]
        )
        return routes

    def _revoke_pair(self, access_token_str: str = None, refresh_token_str: str = None):
        if access_token_str:
            refresh_token = self._access_to_refresh.pop(access_token_str, None)
            self.access_tokens.pop(access_token_str, None)
            if refresh_token:
                self.refresh_tokens.pop(refresh_token, None)
                self._refresh_to_access.pop(refresh_token, None)
        if refresh_token_str:
            access_token = self._refresh_to_access.pop(refresh_token_str, None)
            self.refresh_tokens.pop(refresh_token_str, None)
            if access_token:
                self.access_tokens.pop(access_token, None)
                self._access_to_refresh.pop(access_token, None)
