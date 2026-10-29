"""Authenticate the gateway-to-backend hop independently of browser sessions."""

import hmac
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from app.domain.tools.host_capabilities import HOST_CAPABILITIES


GATEWAY_TOKEN_ENV = "TIANCE_GATEWAY_INTERNAL_TOKEN"
GATEWAY_TOKEN_HEADER = b"x-tiance-gateway-token"
# These exact tool endpoints have their own scoped, short-lived capability grants.
# Do not exempt a router prefix: its ordinary UI endpoints still require the gateway.
CAPABILITY_ENDPOINTS = frozenset('/api' + definition.path for definition in HOST_CAPABILITIES.values())


class GatewayAuthenticationMiddleware:
    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self._token = token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method")
        public = scope["type"] == "http" and method in {"GET", "HEAD"} and (
            path == "/api/health" or path == "/app" or path.startswith("/app/")
        )
        capability = scope["type"] == "http" and method == "POST" and path in CAPABILITY_ENDPOINTS
        supplied = [value for key, value in scope.get("headers", []) if key.lower() == GATEWAY_TOKEN_HEADER]
        authorized = bool(self._token) and len(supplied) == 1 and hmac.compare_digest(supplied[0], self._token)
        if public or capability or authorized:
            # Do not expose the internal credential to routes, tool bridges or logging.
            scope = dict(scope, headers=[(key, value) for key, value in scope.get("headers", []) if key.lower() != GATEWAY_TOKEN_HEADER])
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await JSONResponse({"error": {"code": "GATEWAY_AUTHENTICATION_REQUIRED", "message": "请通过天策访问网关连接。"}}, status_code=401)(scope, receive, send)
