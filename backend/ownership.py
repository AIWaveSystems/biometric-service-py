from fastapi import HTTPException, Request
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .models import User


def api_client_id(request: Request) -> int | None:
    return getattr(request.state, "client_id", None)


def scope_user_query(query: Select, request: Request, user_column) -> Select:
    client_id = api_client_id(request)
    if client_id is not None:
        return query.where(user_column.api_client_id == client_id)
    return query


def scope_new_username(query: Select, request: Request, user_column) -> Select:
    client_id = api_client_id(request)
    if client_id is not None:
        return query.where(user_column.api_client_id == client_id)
    return query.where(user_column.api_client_id.is_(None))


def resolve_user_by_username(db: Session, request: Request | None, username: str) -> User:
    query = select(User).where(User.username == username)
    client_id = api_client_id(request) if request is not None else None
    if client_id is not None:
        query = query.where(User.api_client_id == client_id)
    matches = db.execute(query).scalars().all()
    if not matches:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ese nombre de usuario existe en varios sistemas cliente. "
                "Usa las rutas por UUID para indicar a cual te refieres."
            ),
        )
    return matches[0]
