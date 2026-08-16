from fastapi import HTTPException, Request

from .security import auth_limiter


def client_host(request: Request) -> str:
    return request.client.host if request.client else "desconocido"


def check_biometric_rate(request: Request, kind: str, username: str) -> None:
    key = f"{kind}:{client_host(request)}:{username}"
    if not auth_limiter.allow(key):
        raise HTTPException(status_code=429, detail="Demasiados intentos, espera un momento")
