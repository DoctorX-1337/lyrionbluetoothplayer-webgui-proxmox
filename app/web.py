import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.auth import Auth
from app.config import Config
from app.database import DeviceRepository
from app.errors import PlayerError


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class Password(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


def create_app(config=None, transport=None):
    config = config or Config.load()
    repo = DeviceRepository(config.database)
    auth = Auth(repo, config)
    static = Path(__file__).parent / "static"

    @asynccontextmanager
    async def lifespan(app):
        yield
        repo.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth = auth
    app.state.repo = repo
    internal_transport = transport or httpx.AsyncHTTPTransport(uds=config.socket)

    @app.middleware("http")
    async def security(request, call_next):
        path = request.url.path
        session = auth.session(request.cookies.get("lyrion_session"))
        request.state.session = session
        mutating = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if mutating:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Die Anfrage stammt von einer anderen Webseite."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Webseitenübergreifende Anfrage abgelehnt."}, status_code=403)
            if path != "/api/auth/login":
                expected = session["csrf"] if session else request.cookies.get("lyrion_csrf", "") if not config.auth_enabled else ""
                supplied = request.headers.get("x-csrf-token", "")
                if not expected or not hmac.compare_digest(expected, supplied):
                    return JSONResponse({"detail": "Sitzung abgelaufen oder CSRF-Token fehlt."}, status_code=403)
        public_api = path in {"/api/auth/login", "/api/auth/session"}
        if path.startswith("/api/") and not public_api and config.auth_enabled:
            if not session:
                return JSONResponse({"detail": "Bitte zuerst anmelden."}, status_code=401)
            if session["must_change"] and path not in {"/api/auth/password", "/api/auth/logout"}:
                return JSONResponse({"detail": "Bitte zuerst das Initialpasswort ändern.", "must_change": True}, status_code=403)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(PlayerError)
    async def error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=429 if exc.code == "rate_limit" else 401 if exc.code == "login_failed" else 400)

    @app.get("/api/auth/session")
    async def session(request: Request):
        if not config.auth_enabled:
            import secrets
            csrf = request.cookies.get("lyrion_csrf") or secrets.token_urlsafe(24)
            response = JSONResponse({"authenticated": True, "csrf": csrf, "must_change": False, "auth_enabled": False})
            response.set_cookie("lyrion_csrf", csrf, httponly=True, samesite="strict", secure=config.cookie_secure)
            return response
        return {"authenticated": bool(request.state.session), "auth_enabled": True, **(request.state.session or {})}

    @app.post("/api/auth/login")
    async def login(values: Login, request: Request):
        if not config.auth_enabled:
            raise PlayerError("Anmeldung ist deaktiviert", "invalid")
        token, session = auth.login(values.username, values.password, request.client.host if request.client else "local")
        response = JSONResponse({"authenticated": True, **session})
        response.set_cookie("lyrion_session", token, httponly=True, samesite="strict", secure=config.cookie_secure, max_age=config.session_hours * 3600)
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        auth.logout(request.cookies.get("lyrion_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("lyrion_session")
        return response

    @app.post("/api/auth/password")
    async def password(values: Password, request: Request):
        auth.change_password(values.old_password, values.new_password, request.cookies.get("lyrion_session", ""))
        return {"ok": True}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(path: str, request: Request):
        url = "http://manager/api/" + path
        timeout = httpx.Timeout(150, connect=3)
        if path == "events":
            async def stream():
                try:
                    async with httpx.AsyncClient(transport=internal_transport, timeout=None) as client:
                        async with client.stream("GET", url) as result:
                            async for chunk in result.aiter_bytes():
                                if await request.is_disconnected():
                                    break
                                if config.auth_enabled and not auth.session(request.cookies.get("lyrion_session")):
                                    break
                                yield chunk
                except httpx.HTTPError:
                    yield 'event: offline\ndata: {}\n\n'
            return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        try:
            async with httpx.AsyncClient(transport=internal_transport, timeout=timeout) as client:
                response = await client.request(request.method, url, params=request.query_params, content=await request.body(), headers={"Content-Type": request.headers.get("content-type", "application/json")})
                return JSONResponse(response.json(), status_code=response.status_code)
        except (httpx.HTTPError, ValueError):
            return JSONResponse({"detail": "Der Player-Manager ist nicht erreichbar. Prüfen Sie den Dienst lyrion-bt-manager."}, status_code=503)

    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(static / "favicon" / "favicon.ico")

    @app.get("/{page:path}", include_in_schema=False)
    async def page(page: str):
        if page not in {"", "bluetooth", "audio", "lyrion", "diagnostics", "settings", "login"}:
            return JSONResponse({"detail": "Seite nicht gefunden"}, status_code=404)
        return FileResponse(static / "index.html")

    return app
