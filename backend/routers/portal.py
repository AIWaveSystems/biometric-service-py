from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import PortalUser
from ..security import auth_limiter, create_portal_token, decode_token

router = APIRouter(prefix="/api/portal", tags=["portal"])
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_DUMMY_HASH = pwd.hash("contrasena-invalida-de-relleno")


class PortalLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class PortalUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=256)


class PortalPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


def ensure_bootstrap_user(db: Session) -> None:
    if not settings.portal_user or not settings.portal_password:
        return
    existing = db.execute(select(PortalUser).limit(1)).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        PortalUser(
            username=settings.portal_user,
            password_hash=pwd.hash(settings.portal_password),
            is_bootstrap=True,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


@router.post("/auth")
def portal_auth(body: PortalLogin, request: Request, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "desconocido"
    if not auth_limiter.allow(f"portal:{client}"):
        raise HTTPException(status_code=429, detail="Demasiados intentos, espera un momento")

    account = db.execute(
        select(PortalUser).where(PortalUser.username == body.username)
    ).scalar_one_or_none()
    stored = account.password_hash if account is not None else _DUMMY_HASH
    valid = pwd.verify(body.password, stored)

    if account is None or not account.active or not valid:
        raise HTTPException(status_code=401, detail="Credenciales de acceso invalidas")

    account.last_login_at = datetime.utcnow()
    db.commit()

    return {
        "access_token": create_portal_token(account.username, str(account.uuid)),
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "username": account.username,
        "uuid": str(account.uuid),
    }


@router.get("/me")
def portal_me(request: Request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Acceso no autorizado")
    payload = decode_token(header[7:], expected_scope="portal")
    if payload is None:
        raise HTTPException(status_code=401, detail="Acceso no autorizado")
    return {
        "username": payload.get("sub"),
        "uuid": payload.get("uid"),
        "scope": payload.get("scope"),
        "auth": "portal",
    }


@router.get("/users")
def list_portal_users(db: Session = Depends(get_db)):
    rows = db.execute(select(PortalUser).order_by(PortalUser.username)).scalars().all()
    return [
        {
            "uuid": str(u.uuid),
            "username": u.username,
            "active": u.active,
            "is_bootstrap": u.is_bootstrap,
            "created_at": u.created_at,
            "last_login_at": u.last_login_at,
        }
        for u in rows
    ]


@router.post("/users", status_code=201)
def create_portal_user(body: PortalUserCreate, db: Session = Depends(get_db)):
    account = PortalUser(username=body.username, password_hash=pwd.hash(body.password))
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un usuario de portal con ese nombre")
    db.refresh(account)
    return {"uuid": str(account.uuid), "username": account.username, "active": account.active}


@router.post("/users/{user_uuid}/disable")
def disable_portal_user(user_uuid: str, db: Session = Depends(get_db)):
    account = db.execute(
        select(PortalUser).where(PortalUser.uuid == user_uuid)
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Usuario de portal no encontrado")

    remaining = db.execute(
        select(PortalUser).where(PortalUser.active.is_(True), PortalUser.uuid != user_uuid)
    ).scalars().all()
    if not remaining:
        raise HTTPException(
            status_code=409, detail="No puedes desactivar el ultimo usuario de portal activo"
        )

    account.active = False
    db.commit()
    return {"disabled": str(account.uuid), "username": account.username}


@router.post("/users/{user_uuid}/password")
def change_portal_password(
    user_uuid: str, body: PortalPasswordChange, db: Session = Depends(get_db)
):
    account = db.execute(
        select(PortalUser).where(PortalUser.uuid == user_uuid)
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Usuario de portal no encontrado")
    if not pwd.verify(body.current_password, account.password_hash):
        raise HTTPException(status_code=401, detail="La contrasena actual no es correcta")
    account.password_hash = pwd.hash(body.new_password)
    account.is_bootstrap = False
    db.commit()
    return {"username": account.username, "message": "Contrasena actualizada"}
