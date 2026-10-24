"""Request guards run before parsing uploads or invoking external services.

The shared access code is stored only as a salted scrypt hash (`ACCESS_CODE_HASH`). A correct
code posted to `/api/session` earns a signed, expiring, HttpOnly cookie, so the browser never
keeps the code. Run `uv run python -m gae.security hash-access-code` to make the hash.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from gae.settings import Settings, get_settings

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
OPEN_PATHS = frozenset({"/api/health", "/api/session"})
SESSION_COOKIE = "gae_session"
MIN_SESSION_SECRET_BYTES = 32
# 32 MiB and roughly 0.1-0.3 s per check on one Cloud Run vCPU (OWASP-equivalent strength).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 3
SCRYPT_MAXMEM = 64 * 1024 * 1024
MAX_SESSION_BODY = 4096
# Tolerate small clock differences between instances when checking the issue time.
CLOCK_SKEW_SECONDS = 300
MAX_TRACKED_IPS = 10000
UNAUTHORISED = {"detail": "Access code required or incorrect."}


def hash_access_code(code: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        code.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=32,
    )
    encoded = (base64.b64encode(part).decode() for part in (salt, digest))
    return "$".join(["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), *encoded])


@dataclass(frozen=True)
class AccessHash:
    n: int
    r: int
    p: int
    salt: bytes
    digest: bytes

    @classmethod
    def parse(cls, value: str) -> AccessHash:
        try:
            scheme, n, r, p, salt, digest = value.strip().split("$")
            if scheme != "scrypt":
                raise ValueError(scheme)
            parsed = cls(
                int(n),
                int(r),
                int(p),
                base64.b64decode(salt, validate=True),
                base64.b64decode(digest, validate=True),
            )
        except ValueError:
            parsed = None
        if (
            parsed is None
            or parsed.n < 2
            or parsed.n & (parsed.n - 1)
            or not 1 <= parsed.r * parsed.p <= 64
            or 128 * parsed.n * parsed.r > SCRYPT_MAXMEM // 2
            or len(parsed.salt) < 16
            or len(parsed.digest) < 16
        ):
            raise RuntimeError(
                "ACCESS_CODE_HASH is not a valid scrypt hash; "
                "make one with `uv run python -m gae.security hash-access-code`."
            )
        return parsed

    def matches(self, code: str) -> bool:
        candidate = hashlib.scrypt(
            code.encode(),
            salt=self.salt,
            n=self.n,
            r=self.r,
            p=self.p,
            maxmem=SCRYPT_MAXMEM,
            dklen=len(self.digest),
        )
        return hmac.compare_digest(candidate, self.digest)


@dataclass(frozen=True)
class Access:
    code_hash: AccessHash
    # Derived from the hash too, so changing the access code signs every old session out.
    signing_key: bytes
    ttl: int
    secure: bool

    def issue(self, now: float) -> str:
        issued = int(now)
        payload = f"{issued}.{issued + self.ttl}"
        return f"{payload}.{self._sign(payload)}"

    def valid(self, token: str | None, now: float) -> bool:
        try:
            issued, expires, signature = (token or "").split(".")
            if not hmac.compare_digest(signature, self._sign(f"{issued}.{expires}")):
                return False
            issued_at, expires_at = int(issued), int(expires)
        except ValueError:
            return False
        return (
            issued_at <= now + CLOCK_SKEW_SECONDS
            and now < expires_at
            and expires_at - issued_at <= self.ttl
        )

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self.signing_key, payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def load_access(settings: Settings) -> Access | None:
    """None keeps local development open; otherwise refuse unsafe configuration."""
    if settings.access_code is not None:
        raise RuntimeError(
            "ACCESS_CODE is no longer supported; remove it and set ACCESS_CODE_HASH instead."
        )
    configured = settings.access_code_hash and settings.access_code_hash.get_secret_value()
    if not configured:
        return None
    code_hash = AccessHash.parse(configured)
    secret = settings.session_secret.get_secret_value().encode() if settings.session_secret else b""
    if len(secret) < MIN_SESSION_SECRET_BYTES:
        raise RuntimeError(
            f"ACCESS_CODE_HASH is set, so SESSION_SECRET must be at least "
            f"{MIN_SESSION_SECRET_BYTES} bytes; make one with `openssl rand -base64 48`."
        )
    if not settings.session_cookie_secure and os.environ.get("K_SERVICE"):
        raise RuntimeError("SESSION_COOKIE_SECURE=false is only for plain-http localhost.")
    if settings.session_ttl_seconds < 60:
        raise RuntimeError("SESSION_TTL_SECONDS must be at least 60.")
    key = hmac.new(secret, b"gae-session\0" + configured.strip().encode(), hashlib.sha256)
    return Access(
        code_hash, key.digest(), settings.session_ttl_seconds, settings.session_cookie_secure
    )


def visitor_ip(request: Request) -> str:
    # Cloud Run appends the connecting client to XFF. Ignore user-supplied prefixes.
    forwarded = ",".join(request.headers.getlist("x-forwarded-for")).split(",")[-1].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return request.client.host if request.client else "unknown"


class WindowLimit:
    """Fixed per-IP windows, capped to bound memory even when many IPs visit."""

    def __init__(self):
        # Entries are ordered by first request in each window.
        self.visitors: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def take(self, ip: str, limit: int, window: int, busy: str) -> JSONResponse | None:
        """Count one use; a 429 response when the IP has none left."""
        now = time.monotonic()
        while self.visitors and next(iter(self.visitors.values()))[0] + window <= now:
            self.visitors.popitem(last=False)
        started, count = self.visitors.get(ip, (now, 0))
        if count >= limit:
            retry = max(1, int(started + window - now) + 1)
            return JSONResponse(
                {"detail": busy}, status_code=429, headers={"Retry-After": str(retry)}
            )
        # Fail closed on capacity rather than evicting active limits.
        if ip not in self.visitors and len(self.visitors) >= MAX_TRACKED_IPS:
            return JSONResponse(
                {"detail": "Demo is busy. Please try again later."},
                status_code=429,
                headers={"Retry-After": str(window)},
            )
        self.visitors[ip] = (started, count + 1)
        return None

    def refund(self, ip: str) -> None:
        if ip in self.visitors:
            started, count = self.visitors[ip]
            self.visitors[ip] = (started, max(0, count - 1))


async def read_code(request: Request) -> str | None:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_SESSION_BODY:
            return None
    try:
        code = json.loads(body).get("code")
    except ValueError, AttributeError:
        return None
    return code if isinstance(code, str) and code else None


class ApiGuard:
    def __init__(self, app):
        self.app = app
        self.gemini = WindowLimit()
        self.attempts = WindowLimit()
        self.settings: Settings | None = None
        self.access: Access | None = None

    def current_access(self, settings: Settings) -> Access | None:
        if settings is not self.settings:
            self.access, self.settings = load_access(settings), settings
        return self.access

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        path = scope["path"].rstrip("/")
        if not path.startswith("/api/") or path == "/api/health":
            return await self.app(scope, receive, send)
        settings = get_settings()
        access = self.current_access(settings)
        if path == "/api/session":
            if scope["method"] != "POST":
                response = JSONResponse({"detail": "Method Not Allowed"}, status_code=405)
            else:
                response = await self.sign_in(request, access, settings)
            return await response(scope, receive, send)
        if access is None:
            return await self.app(scope, receive, send)
        if not access.valid(request.cookies.get(SESSION_COOKIE), time.time()):
            return await JSONResponse(UNAUTHORISED, status_code=401)(scope, receive, send)
        limit = settings.gemini_requests_per_ip
        if scope["method"] == "POST" and path in GEMINI_PATHS and limit > 0:
            window = max(1, settings.gemini_limit_window_seconds)
            busy = "Demo limit reached. Please try again later."
            refused = self.gemini.take(visitor_ip(request), limit, window, busy)
            if refused:
                return await refused(scope, receive, send)
        return await self.app(scope, receive, send)

    async def sign_in(self, request: Request, access: Access | None, settings: Settings):
        if access is None:
            return JSONResponse({"ok": True})
        ip = visitor_ip(request)
        # Reserve the attempt before checking so parallel guesses cannot exceed the limit.
        refused = self.attempts.take(
            ip,
            max(1, settings.session_attempts_per_ip),
            max(1, settings.session_attempt_window_seconds),
            "Too many attempts. Please wait a few minutes and try again.",
        )
        if refused:
            return refused
        code = await read_code(request)
        if code is None or not await run_in_threadpool(access.code_hash.matches, code):
            return JSONResponse(UNAUTHORISED, status_code=401)
        self.attempts.refund(ip)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            SESSION_COOKIE,
            access.issue(time.time()),
            max_age=access.ttl,
            path="/api",
            secure=access.secure,
            httponly=True,
            samesite="strict",
        )
        return response


def prompt_hash() -> int:
    code = getpass.getpass("Access code: ")
    if not code:
        print("The access code cannot be empty.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat access code: ") != code:
        print("The codes did not match.", file=sys.stderr)
        return 1
    print(hash_access_code(code))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gae.security")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hash-access-code", help="print an ACCESS_CODE_HASH for a typed code")
    parser.parse_args(argv)
    return prompt_hash()


if __name__ == "__main__":
    sys.exit(main())
