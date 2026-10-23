"""Request guards run before parsing uploads or invoking external services."""

import hmac
import ipaddress
import time
from collections import OrderedDict

from starlette.requests import Request
from starlette.responses import JSONResponse

from gae.settings import get_settings

GEMINI_PATHS = frozenset(
    {
        "/api/photos/check",
        "/api/photos/extract",
        "/api/radiators/video",
        "/api/quotes/check",
        "/api/review",
        "/api/analysis",
        "/api/analysis/review",
        "/api/pack/installer-drafts",
    }
)


def visitor_ip(request: Request) -> str:
    # Cloud Run appends the connecting client to XFF. Ignore user-supplied prefixes.
    forwarded = ",".join(request.headers.getlist("x-forwarded-for")).split(",")[-1].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return request.client.host if request.client else "unknown"


class ApiGuard:
    def __init__(self, app):
        self.app = app
        # Fixed windows, capped to bound memory even when many IPs visit.
        self.visitors: OrderedDict[str, tuple[float, int]] = OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = scope["path"].rstrip("/")
        if not path.startswith("/api/") or path == "/api/health":
            return await self.app(scope, receive, send)
        settings = get_settings()
        code = settings.access_code
        if code and code.get_secret_value():
            supplied = request.headers.get("x-access-code", "")
            if not hmac.compare_digest(supplied.encode(), code.get_secret_value().encode()):
                return await JSONResponse(
                    {"detail": "Access code required or incorrect."}, status_code=401
                )(scope, receive, send)
        if code and code.get_secret_value() and scope["method"] == "POST" and path in GEMINI_PATHS:
            limit = settings.gemini_requests_per_ip
            window = max(1, settings.gemini_limit_window_seconds)
            if limit > 0:
                now = time.monotonic()
                # Entries are ordered by first request in each window.
                while self.visitors and next(iter(self.visitors.values()))[0] + window <= now:
                    self.visitors.popitem(last=False)
                ip = visitor_ip(request)
                started, count = self.visitors.get(ip, (now, 0))
                if count >= limit:
                    retry = max(1, int(started + window - now) + 1)
                    return await JSONResponse(
                        {"detail": "Demo limit reached. Please try again later."},
                        status_code=429,
                        headers={"Retry-After": str(retry)},
                    )(scope, receive, send)
                # Fail closed on capacity rather than evicting active limits.
                if ip not in self.visitors and len(self.visitors) >= 10000:
                    return await JSONResponse(
                        {"detail": "Demo is busy. Please try again later."},
                        status_code=429,
                        headers={"Retry-After": str(window)},
                    )(scope, receive, send)
                self.visitors[ip] = (started, count + 1)
        return await self.app(scope, receive, send)
