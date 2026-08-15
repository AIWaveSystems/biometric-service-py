import base64
from binascii import Error as B64Error
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, face, portal, users, voice
from .security import SCOPE_PORTAL, constant_time_equals, decode_token

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}
OPEN_API_PATHS = {"/api/portal/auth"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = [
        name
        for name, value in (
            ("PORTAL_USER", settings.portal_user),
            ("PORTAL_PASSWORD", settings.portal_password),
            ("JWT_SECRET", settings.jwt_secret),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Faltan variables en el archivo .env: {', '.join(missing)}")
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Login Biometrico Service", version="0.4.0", lifespan=lifespan)


class DocsBasicAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in DOCS_PATHS:
            unauthorized = JSONResponse(
                {"detail": "Autenticacion requerida"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="docs"'},
            )
            header = request.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return unauthorized
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                user, _, password = decoded.partition(":")
            except (B64Error, UnicodeDecodeError):
                return unauthorized
            if not (
                constant_time_equals(user, settings.docs_user_resolved)
                and constant_time_equals(password, settings.docs_password_resolved)
            ):
                return unauthorized
        return await call_next(request)


class PortalApiAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api/"):
            return await call_next(request)
        if path in OPEN_API_PATHS:
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse({"detail": "Acceso no autorizado"}, status_code=401)
        if decode_token(header[7:], expected_scope=SCOPE_PORTAL) is None:
            return JSONResponse({"detail": "Acceso no autorizado"}, status_code=401)
        return await call_next(request)


app.add_middleware(PortalApiAuth)
app.add_middleware(DocsBasicAuth)

_origins = settings.cors_origin_list
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

app.include_router(portal.router)
app.include_router(face.router)
app.include_router(voice.router)
app.include_router(users.router)
app.include_router(auth.router)


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
