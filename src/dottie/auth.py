"""Sign-in with WorkOS AuthKit, on when WORKOS_CLIENT_ID is set.

WorkOS's sealed sessions: /auth/callback trades the code for tokens and stores them, encrypted with SESSION_SECRET,
in an httponly cookie. Each request checks the access token locally (signature and expiry, against WorkOS's cached
keys); a few minutes after sign-in it expires and is refreshed with the refresh token, which fails once WorkOS ends
the session (sign-out elsewhere, a removed user, the session length set in the dashboard). Signed out, the API
answers 401 and pages redirect to the sign-in. ALLOWED_USERS, when set, is a second list the app checks itself.
"""

import base64
import hashlib
import logging
import secrets
from typing import Annotated, Any, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .api.errors import ApiError
from .config import Settings
from .models import Dottie, Skill

log = logging.getLogger(__name__)

SESSION_COOKIE = "wos_session"
SESSION_MAX_AGE_S = 30 * 24 * 3600  # the cookie's own limit; WorkOS's session length decides sooner
STATE_COOKIE = "auth_state"
STATE_MAX_AGE_S = 600
PUBLIC_PATHS = ("/auth/", "/api/health", "/internal/", "/mcp")  # sign-in, health probe, sandboxes and MCP (own tokens)


class User(BaseModel):
    id: str
    email: str


LOCAL_USER = User(id="local", email="you@localhost")  # who everything belongs to while sign-in is off


def current_user(request: Request) -> User:
    """The signed-in user; the one local user when the app runs without sign-in."""
    return getattr(request.state, "user", None) or LOCAL_USER


UserDep = Annotated[User, Depends(current_user)]


class WorkOSAuth(Protocol):
    """What the app needs from WorkOS (tests pass a fake)."""

    def authorization_url(self, redirect_uri: str, state: str) -> str: ...
    async def sign_in(self, code: str) -> tuple[User, str]: ...  # the user and the sealed session
    async def check(self, sealed: str) -> tuple[User | None, str | None]: ...  # the user, and a refreshed session
    def logout_url(self, sealed: str, return_to: str) -> str | None: ...


def cookie_password(secret: str) -> str:
    """Any SESSION_SECRET string works: it is hashed into the Fernet key WorkOS seals sessions with."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()


def _user(data: dict[str, Any] | None) -> User | None:
    return User(id=data["id"], email=data["email"]) if data else None


class SdkWorkOS:
    def __init__(self, settings: Settings):
        from workos import AsyncWorkOSClient

        self.client = AsyncWorkOSClient(api_key=settings.workos_api_key, client_id=settings.workos_client_id)
        self.password = cookie_password(settings.session_secret)

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        return self.client.user_management.get_authorization_url(
            provider="authkit", redirect_uri=redirect_uri, state=state
        )

    async def sign_in(self, code: str) -> tuple[User, str]:
        from workos.session import seal_session_from_auth_response

        res = await self.client.user_management.authenticate_with_code(code=code)
        user = res.user.to_dict()
        sealed = seal_session_from_auth_response(
            access_token=res.access_token, refresh_token=res.refresh_token, user=user, cookie_password=self.password
        )
        return User(id=res.user.id, email=res.user.email), sealed

    async def check(self, sealed: str) -> tuple[User | None, str | None]:
        from workos.session import AuthenticateWithSessionCookieSuccessResponse as Valid
        from workos.session import RefreshWithSessionCookieSuccessResponse as Refreshed

        session = self.client.user_management.load_sealed_session(session_data=sealed, cookie_password=self.password)
        auth = session.authenticate()
        if isinstance(auth, Valid):
            return _user(auth.user), None
        refreshed = await session.refresh()  # the access token expired (or the cookie is bad: then this fails too)
        if isinstance(refreshed, Refreshed):
            return _user(refreshed.user), refreshed.sealed_session
        return None, None

    def logout_url(self, sealed: str, return_to: str) -> str | None:
        from workos.session import AuthenticateWithSessionCookieSuccessResponse as Valid

        session = self.client.user_management.load_sealed_session(session_data=sealed, cookie_password=self.password)
        auth = session.authenticate()
        if not isinstance(auth, Valid):
            return None
        return self.client.user_management.get_logout_url(session_id=auth.session_id, return_to=return_to)


def adopt_local_data(sessions: sessionmaker[Session], user: User) -> int:
    """What was made before there was sign-in belongs to the one local user. The first person to sign in takes it
    over (once real users own anything, nobody can): returns how many dotties moved."""
    with sessions() as s:
        if s.scalar(select(func.count()).select_from(Dottie).where(Dottie.owner_id != LOCAL_USER.id)):
            return 0
        moved = s.scalar(select(func.count()).select_from(Dottie).where(Dottie.owner_id == LOCAL_USER.id)) or 0
        s.execute(update(Dottie).where(Dottie.owner_id == LOCAL_USER.id).values(owner_id=user.id))
        s.execute(update(Skill).where(Skill.owner_id == LOCAL_USER.id).values(owner_id=user.id))
        s.commit()
        return moved


def _base_url(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return (settings.public_url or str(request.base_url)).rstrip("/")


def _cookie_args(request: Request, max_age: int, path: str = "/") -> dict[str, Any]:
    # behind a TLS-terminating proxy the request itself is http: PUBLIC_URL says https
    secure = _base_url(request).startswith("https://")
    return {"max_age": max_age, "path": path, "httponly": True, "secure": secure, "samesite": "lax"}


def _safe_next(path: str | None) -> str:
    """Only paths on this site, so the sign-in can't bounce people elsewhere."""
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


class AuthMiddleware:
    """Plain ASGI (not BaseHTTPMiddleware), so streaming responses pass through untouched. Puts the user in
    request.state.user, and a refreshed session into the response's cookie."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = request.url.path
        if path.startswith(PUBLIC_PATHS):
            return await self.app(scope, receive, send)

        settings: Settings = request.app.state.settings
        user, refreshed = None, None
        if sealed := request.cookies.get(SESSION_COOKIE):
            user, refreshed = await request.app.state.workos.check(sealed)
        if user and settings.user_allowed(user.email):
            scope.setdefault("state", {})["user"] = user
            return await self.app(scope, receive, _with_cookie(send, request, refreshed) if refreshed else send)

        if path.startswith("/api/"):
            res: Response = JSONResponse({"error": {"code": "unauthenticated", "message": "Sign in first."}}, 401)
        else:
            target = path + (f"?{request.url.query}" if request.url.query else "")
            res = RedirectResponse(f"/auth/login?next={quote(target)}", 303)
        return await res(scope, receive, send)


def _with_cookie(send: Send, request: Request, sealed: str) -> Send:
    """send, with the refreshed session cookie added to the response."""
    cookie = Response()
    cookie.set_cookie(SESSION_COOKIE, sealed, **_cookie_args(request, SESSION_MAX_AGE_S))

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            MutableHeaders(scope=message).append("set-cookie", cookie.headers["set-cookie"])
        await send(message)

    return wrapped


def build_router() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/auth/login")
    async def login(request: Request, next: str = "/") -> Response:
        state = secrets.token_urlsafe(24)
        url = request.app.state.workos.authorization_url(f"{_base_url(request)}/auth/callback", state)
        res = RedirectResponse(url, 303)
        res.set_cookie(STATE_COOKIE, f"{state}:{_safe_next(next)}", **_cookie_args(request, STATE_MAX_AGE_S, "/auth"))
        return res

    @router.get("/auth/callback")
    async def callback(request: Request, code: str = "", state: str = "") -> Response:
        saved_state, _, next_path = request.cookies.get(STATE_COOKIE, "").partition(":")
        if not code or not saved_state or not secrets.compare_digest(saved_state, state):
            return RedirectResponse("/auth/login", 303)  # an old or replayed link: start over
        try:
            user, sealed = await request.app.state.workos.sign_in(code)
        except Exception as e:
            log.exception("WorkOS refused the sign-in")
            raise ApiError(
                "signin_failed",
                "WorkOS refused the sign-in. Check that WORKOS_CLIENT_ID and WORKOS_API_KEY belong to the same "
                f"WorkOS application. ({type(e).__name__})",
                502,
            ) from e
        if not request.app.state.settings.user_allowed(user.email):
            raise ApiError("forbidden", f"{user.email} may not use this app.", 403)
        adopt_local_data(request.app.state.session_factory, user)
        res = RedirectResponse(_safe_next(next_path), 303)
        res.delete_cookie(STATE_COOKIE, path="/auth")
        res.set_cookie(SESSION_COOKIE, sealed, **_cookie_args(request, SESSION_MAX_AGE_S))
        return res

    @router.get("/auth/logout")
    async def logout(request: Request) -> Response:
        home = f"{_base_url(request)}/"
        sealed = request.cookies.get(SESSION_COOKIE)
        res = RedirectResponse((sealed and request.app.state.workos.logout_url(sealed, home)) or home, 303)
        res.delete_cookie(SESSION_COOKIE)
        return res

    return router


class MeOut(BaseModel):
    user: User | None


me_router = APIRouter()


@me_router.get("/me")
def me(request: Request) -> MeOut:
    """Who is signed in; null when sign-in is off."""
    return MeOut(user=getattr(request.state, "user", None))
