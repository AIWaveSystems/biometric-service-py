from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..ownership import resolve_user_by_username
from ..schemas import TokenResponse
from ..security import auth_limiter, create_session_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_DUMMY_HASH = pwd.hash("login-biometrico-dummy")


class PasswordLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login", response_model=TokenResponse)
def login(body: PasswordLogin, request: Request, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "desconocido"
    if not auth_limiter.allow(f"password:{client}:{body.username}"):
        raise HTTPException(status_code=429, detail="Demasiados intentos, espera un momento")

    user = resolve_user_by_username(db, request, body.username)
    stored = user.password_hash if user and user.password_hash else _DUMMY_HASH
    valid = pwd.verify(body.password, stored)

    if user is None or user.password_hash is None or not valid:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")

    return TokenResponse(
        access_token=create_session_token(user.username, "password", str(user.uuid)),
        expires_in=settings.session_expire_minutes * 60,
    )
