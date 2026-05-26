"""API 鉴权中间件：保护写操作端点"""
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# 需要鉴权的路径前缀
PROTECTED_PATHS = [
    "/api/portfolio/buy",
    "/api/portfolio/sell",
    "/api/portfolio/init",
    "/api/admin/",
]


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = os.environ.get("API_SECRET_KEY")
        if not api_key:
            return await call_next(request)

        path = request.url.path
        method = request.method

        needs_auth = False
        for protected in PROTECTED_PATHS:
            if path.startswith(protected):
                needs_auth = True
                break

        # POST/PUT /api/watchlist 和 /api/notification/config 也需要鉴权
        if not needs_auth and method in ("POST", "PUT"):
            if path.startswith("/api/watchlist") or path.startswith("/api/notification/config"):
                needs_auth = True

        if needs_auth:
            provided_key = request.headers.get("X-API-Key", "")
            if provided_key != api_key:
                raise HTTPException(status_code=401, detail="Invalid or missing API key")

        return await call_next(request)
