from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api_clients import invalidate_cache
from ..config import settings
from ..database import get_db
from ..models import ApiClient
from ..schemas import PaginationParams
from ..security import generate_api_key
from ..utils.pagination import paginate, paginated_response

router = APIRouter(prefix="/api/clients", tags=["clients"])

VALID_SCOPES = {"auth", "enroll", "admin"}


class ClientCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["auth"])
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


@router.post("", status_code=201)
def create_client(body: ClientCreate, request: Request, db: Session = Depends(get_db)):
    unknown = set(body.scopes) - VALID_SCOPES
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Permisos desconocidos: {', '.join(sorted(unknown))}. "
            f"Validos: {', '.join(sorted(VALID_SCOPES))}",
        )
    if not body.scopes:
        raise HTTPException(status_code=400, detail="Se requiere al menos un permiso")

    days = body.expires_in_days if body.expires_in_days is not None else settings.api_key_default_days
    expires_at = datetime.utcnow() + timedelta(days=days) if days > 0 else None

    raw_key, prefix, key_hash = generate_api_key()
    client = ApiClient(
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=",".join(body.scopes),
        expires_at=expires_at,
        created_by=getattr(request.state, "principal", None),
    )
    db.add(client)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un cliente con ese nombre")
    db.refresh(client)

    return {
        "uuid": str(client.uuid),
        "name": client.name,
        "scopes": client.scope_list,
        "expires_at": client.expires_at,
        "api_key": raw_key,
        "aviso": "Guarda esta API key ahora: no se puede volver a consultar.",
    }


@router.get("")
def list_clients(
    page: int | None = Query(default=None, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    sort_by: str = Query(default="name", max_length=50),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    params = PaginationParams(
        page=page or 1, limit=limit, search=search, sort_by=sort_by, sort_dir=sort_dir
    )

    def serialize(rows):
        return [
        {
            "uuid": str(c.uuid),
            "name": c.name,
            "key_prefix": c.key_prefix,
            "scopes": c.scope_list,
            "active": c.active,
            "expired": c.expired,
            "usable": c.usable,
            "created_at": c.created_at,
            "expires_at": c.expires_at,
            "last_used_at": c.last_used_at,
            "created_by": c.created_by,
        }
        for c in rows
        ]

    if page is None and search is None and sort_by == "name" and sort_dir == "asc":
        rows = db.execute(select(ApiClient).order_by(ApiClient.name)).scalars().all()
        return serialize(rows)
    try:
        rows, meta = paginate(
            db,
            select(ApiClient),
            params,
            (ApiClient.name, ApiClient.key_prefix),
            {
                "name": ApiClient.name,
                "created_at": ApiClient.created_at,
                "expires_at": ApiClient.expires_at,
                "last_used_at": ApiClient.last_used_at,
                "active": ApiClient.active,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return paginated_response(serialize(rows), meta)


@router.post("/{client_uuid}/revoke")
def revoke_client(client_uuid: str, db: Session = Depends(get_db)):
    client = db.execute(
        select(ApiClient).where(ApiClient.uuid == client_uuid)
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client.active = False
    db.commit()
    invalidate_cache(client.key_prefix)
    return {"revoked": str(client.uuid), "name": client.name}


@router.post("/{client_uuid}/rotate")
def rotate_client(
    client_uuid: str,
    expires_in_days: int | None = None,
    db: Session = Depends(get_db),
):
    days = expires_in_days
    client = db.execute(
        select(ApiClient).where(ApiClient.uuid == client_uuid)
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    old_prefix = client.key_prefix
    raw_key, prefix, key_hash = generate_api_key()
    client.key_prefix = prefix
    client.key_hash = key_hash
    client.active = True
    if days is not None:
        client.expires_at = datetime.utcnow() + timedelta(days=days) if days > 0 else None
    db.commit()
    invalidate_cache(old_prefix)
    invalidate_cache(prefix)
    return {
        "uuid": str(client.uuid),
        "name": client.name,
        "api_key": raw_key,
        "expires_at": client.expires_at,
        "aviso": "La API key anterior queda invalidada de inmediato.",
    }
