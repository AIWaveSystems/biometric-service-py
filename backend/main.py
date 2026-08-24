import base64
import logging
from binascii import Error as B64Error
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from .api_clients import resolve_api_key
from .biometrics.face import embedder
from .biometrics.face import landmarks as face_landmarks
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .routers import auth, clients, face, portal, users, voice
from .routers.portal import ensure_bootstrap_user
from .security import SCOPE_PORTAL, constant_time_equals, decode_token

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}
OPEN_API_PATHS = {"/api/portal/auth"}

SCOPE_ENROLL = "enroll"
SCOPE_AUTH = "auth"
SCOPE_ADMIN = "admin"

ENROLL_PATHS = {
    "/api/users/register",
    "/api/face/register",
    "/api/voice/register",
    "/api/voice/digits/enroll",
}
ADMIN_PREFIXES = ("/api/clients", "/api/portal/users")
ADMIN_PATHS = {"/api/users", "/api/face/templates", "/api/voice/templates", "/api/voice/system"}


def required_scope(method: str, path: str) -> str:
    if path in ENROLL_PATHS:
        return SCOPE_ENROLL
    if path.startswith("/api/users/") and path.endswith("/faces"):
        return SCOPE_ENROLL
    if path.startswith("/api/users/") and path.endswith(("/password", "/rename")):
        return SCOPE_ADMIN
    if path.startswith(ADMIN_PREFIXES):
        return SCOPE_ADMIN
    if path in ADMIN_PATHS or path.startswith(("/api/face/templates/", "/api/voice/templates/")):
        return SCOPE_ADMIN
    if method == "DELETE" and path.startswith(("/api/users/", "/api/voice/digits/")):
        return SCOPE_ADMIN
    return SCOPE_AUTH


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
    if not (embedder.available() and face_landmarks.available()):
        raise RuntimeError(
            "Faltan los modelos ONNX de reconocimiento facial. "
            "Ejecuta: python scripts/fetch_models.py"
        )
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_bootstrap_user(db)
    finally:
        db.close()
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

        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            db = SessionLocal()
            try:
                resolved = await run_in_threadpool(resolve_api_key, db, api_key)
            finally:
                db.close()
            if resolved is None:
                return JSONResponse({"detail": "API key invalida"}, status_code=401)
            client_id, prefix, scopes = resolved
            needed = required_scope(request.method, path)
            if needed not in scopes:
                return JSONResponse(
                    {"detail": f"La API key no tiene el permiso '{needed}'"}, status_code=403
                )
            request.state.client_id = client_id
            request.state.client_prefix = prefix
            request.state.principal = f"apikey:{prefix}"
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse({"detail": "Acceso no autorizado"}, status_code=401)
        payload = decode_token(header[7:], expected_scope=SCOPE_PORTAL)
        if payload is None:
            return JSONResponse({"detail": "Acceso no autorizado"}, status_code=401)
        request.state.client_id = None
        request.state.client_prefix = "portal"
        request.state.principal = str(payload.get("sub", "portal"))
        return await call_next(request)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
        "font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        skip_csp = request.url.path in DOCS_PATHS
        for name, value in SECURITY_HEADERS.items():
            if skip_csp and name == "Content-Security-Policy":
                continue
            response.headers.setdefault(name, value)
        return response


app.add_middleware(PortalApiAuth)
app.add_middleware(DocsBasicAuth)
app.add_middleware(SecurityHeaders)

_origins = settings.cors_origin_list
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

app.include_router(portal.router)
app.include_router(clients.router)
app.include_router(face.router)
app.include_router(voice.router)
app.include_router(users.router)
app.include_router(auth.router)


@app.get("/health")
def health(db=Depends(get_db)):
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    models_ok = embedder.available() and face_landmarks.available()
    status = "ok" if db_ok and models_ok else "degraded"
    code = 200 if status == "ok" else 503
    return JSONResponse(
        {
            "status": status,
            "database": db_ok,
            "face_models": models_ok,
            "version": app.version,
        },
        status_code=code,
    )


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
