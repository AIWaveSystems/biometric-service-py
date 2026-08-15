from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..security import auth_limiter, constant_time_equals, create_portal_token

router = APIRouter(prefix="/api/portal", tags=["portal"])


class PortalLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth")
def portal_auth(body: PortalLogin, request: Request):
    client = request.client.host if request.client else "desconocido"
    if not auth_limiter.allow(f"portal:{client}"):
        raise HTTPException(status_code=429, detail="Demasiados intentos, espera un momento")

    if not settings.portal_user or not settings.portal_password:
        raise HTTPException(
            status_code=500,
            detail="Portal no configurado: faltan PORTAL_USER/PORTAL_PASSWORD en .env",
        )

    user_ok = constant_time_equals(body.username, settings.portal_user)
    password_ok = constant_time_equals(body.password, settings.portal_password)
    if not (user_ok and password_ok):
        raise HTTPException(status_code=401, detail="Credenciales de acceso invalidas")

    return {
        "access_token": create_portal_token(),
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
    }
