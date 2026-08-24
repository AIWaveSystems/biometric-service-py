from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..biometrics.face import detector, embedder, quality
from ..config import settings
from ..database import get_db
from ..models import ApiClient, FaceTemplate, User
from ..ownership import (
    api_client_id,
    resolve_user,
    scope_new_username,
    scope_user_query,
)
from ..schemas import PaginationParams, UserResponse, VoiceRegisterResponse
from ..utils.pagination import paginate, paginated_response
from .voice import build_template, find_duplicate_voice

router = APIRouter(prefix="/api/users", tags=["users"])
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_DIGIT_MIN = settings.voice_challenge_digits + 1


def _user_response(u: User) -> UserResponse:
    digits = sorted(t.digit for t in u.digit_templates)
    cmvn_ok = bool(u.digit_templates) and all(t.cmvn for t in u.digit_templates)
    return UserResponse(
        username=u.username,
        uuid=str(u.uuid),
        has_password=bool(u.password_hash),
        face_templates=[{"id": t.id, "algorithm": t.algorithm} for t in u.face_templates],
        voice_templates=[
            {
                "id": t.id,
                "algorithm": t.algorithm,
                "duration_seconds": t.duration_seconds,
            }
            for t in u.voice_templates
        ],
        digits=digits,
        digits_challenge_ready=len(digits) >= _DIGIT_MIN and cmvn_ok,
        digits_cmvn_ok=cmvn_ok,
        owner=(
            {"name": u.api_client.name, "key_prefix": u.api_client.key_prefix}
            if u.api_client is not None
            else None
        ),
    )


@router.post("/register")
def register(
    request: Request,
    username: str = Form(..., min_length=3, max_length=100),
    password: str | None = Form(default=None, min_length=6, max_length=128),
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] = File(default=[]),
    audio: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    existing_query = scope_new_username(select(User).where(User.username == username), request, User)
    existing = db.execute(existing_query).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    face_files = ([image] if image is not None else []) + list(images)
    if not face_files and audio is None and not password:
        raise HTTPException(
            status_code=400, detail="Se requiere al menos una biometria o una contrasena"
        )

    user = User(
        username=username,
        api_client_id=api_client_id(request),
        password_hash=pwd.hash(password) if password else None,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    registered = []
    if face_files:
        n_faces = 0
        rejected = None
        accepted: list = []
        n_redundant = 0
        for upload in face_files:
            img = detector.load_image(upload.file.read())
            face = embedder.primary_face(img)
            if face is None:
                continue
            rect = embedder.face_rect(face, img.shape)
            normalized = detector.normalize_face(img, rect)
            problem = quality.check(quality.measure(normalized, rect))
            if problem is not None:
                rejected = problem
                continue
            vector = embedder.embed(img, face)
            if quality.is_redundant(vector, accepted):
                n_redundant += 1
                continue
            accepted.append(vector)
            db.add(
                FaceTemplate(user_id=user.id, algorithm="sface", features=vector.tobytes())
            )
            n_faces += 1
        if n_faces == 0:
            raise HTTPException(
                status_code=400,
                detail=rejected or "No se detecto ninguna cara en las imagenes",
            )
        registered.append(f"cara x{n_faces}")
        if n_redundant:
            registered.append(f"{n_redundant} foto(s) descartada(s) por ser casi identicas")

    voice_result = None
    if audio is not None:
        template, n_components, duration, n_frames = build_template(user.id, audio.file.read())

        duplicado = find_duplicate_voice(
            db, template.embedding, user.id, api_client_id(request)
        )
        if duplicado is not None and settings.voice_reject_duplicates:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "Esa voz ya esta matriculada en otra cuenta "
                    f"(similitud {duplicado[1]:.3f}). El usuario no se ha creado."
                ),
            )
        if duplicado is not None:
            registered.append("AVISO: la voz se parece a la de otra cuenta existente")
        db.add(template)
        voice_result = VoiceRegisterResponse(
            username=username,
            algorithm="mfcc-gmm",
            n_components=n_components,
            duration_seconds=round(duration, 2),
            n_frames=n_frames,
            message="voz",
        )
        registered.append("voz")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    db.refresh(user)
    return {
        "username": username,
        "uuid": str(user.uuid),
        "registered": registered,
        "password": bool(password),
        "voice": voice_result.model_dump() if voice_result else None,
    }


@router.get("", response_model=list[UserResponse] | dict)
def list_users(
    page: int | None = Query(default=None, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    owner: str | None = Query(default=None, max_length=64),
    sort_by: str = Query(default="username", max_length=50),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    params = PaginationParams(
        page=page or 1, limit=limit, search=search, sort_by=sort_by, sort_dir=sort_dir
    )
    query = select(User)
    if owner is not None:
        query = _filter_by_owner(db, query, owner)
    fast_path = (
        page is None and search is None and owner is None and sort_by == "username" and sort_dir == "asc"
    )
    if fast_path:
        users = db.execute(query.order_by(User.username)).scalars().all()
        return [_user_response(u) for u in users]
    try:
        users, meta = paginate(
            db,
            query,
            params,
            (User.username,),
            {"username": User.username, "created_at": User.created_at, "uuid": User.uuid},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return paginated_response([_user_response(u) for u in users], meta)


def _filter_by_owner(db: Session, query, owner: str):
    if owner == "portal":
        return query.where(User.api_client_id.is_(None))
    try:
        client_uuid = UUID(owner)
    except ValueError:
        raise HTTPException(status_code=400, detail="Sistema cliente desconocido")
    client = db.execute(select(ApiClient).where(ApiClient.uuid == client_uuid)).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=400, detail="Sistema cliente desconocido")
    return query.where(User.api_client_id == client.id)


@router.get("/by-uuid/{user_uuid}", response_model=UserResponse)
def get_by_uuid(user_uuid: str, request: Request, db: Session = Depends(get_db)):
    query = scope_user_query(select(User).where(User.uuid == user_uuid), request, User)
    user = db.execute(query).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return _user_response(user)


def _get_user(
    db: Session, username: str, request: Request | None = None, user_uuid: str | None = None
) -> User:
    return resolve_user(db, request, username, user_uuid)


@router.post("/{username}/faces")
def add_faces(
    request: Request,
    username: str,
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username, request)
    uploads = ([image] if image is not None else []) + list(images)
    if not uploads:
        raise HTTPException(status_code=400, detail="No se envio ninguna imagen")

    accepted = [
        np.frombuffer(t.features, dtype=np.float32)
        for t in user.face_templates
        if t.algorithm == "sface"
    ]
    n_existing = len(accepted)

    added = 0
    n_redundant = 0
    n_no_face = 0
    rejected: str | None = None
    for upload in uploads:
        img = detector.load_image(upload.file.read())
        face = embedder.primary_face(img)
        if face is None:
            n_no_face += 1
            continue
        rect = embedder.face_rect(face, img.shape)
        problem = quality.check(quality.measure(detector.normalize_face(img, rect), rect))
        if problem is not None:
            rejected = problem
            continue
        vector = embedder.embed(img, face)
        if quality.is_redundant(vector, accepted):
            n_redundant += 1
            continue
        accepted.append(vector)
        db.add(FaceTemplate(user_id=user.id, algorithm="sface", features=vector.tobytes()))
        added += 1

    if added == 0:
        db.rollback()
        detail = rejected or (
            "Todas las fotos son casi identicas a las que ya tiene el usuario"
            if n_redundant
            else "No se detecto ninguna cara en las imagenes"
        )
        raise HTTPException(status_code=400, detail=detail)

    db.commit()
    return {
        "username": username,
        "uuid": str(user.uuid),
        "added": added,
        "redundant": n_redundant,
        "without_face": n_no_face,
        "total_templates": n_existing + added,
    }


@router.post("/{username}/password")
def set_password(
    request: Request,
    username: str,
    password: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username, request)
    if password is not None and password != "" and len(password) < 6:
        raise HTTPException(status_code=400, detail="La contrasena debe tener 6 caracteres o mas")

    user.password_hash = pwd.hash(password) if password else None
    db.commit()
    return {"username": username, "uuid": str(user.uuid), "has_password": bool(user.password_hash)}


@router.post("/{username}/rename")
def rename_user(
    request: Request,
    username: str,
    new_username: str = Form(..., min_length=3, max_length=100),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username, request)
    if new_username == username:
        raise HTTPException(status_code=400, detail="El nombre nuevo es el mismo")

    user.username = new_username
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese nombre")

    return {"username": new_username, "previous": username, "uuid": str(user.uuid)}


@router.delete("/{username}")
def delete_user(username: str, request: Request, db: Session = Depends(get_db)):
    user = resolve_user(db, request, username)
    deleted_uuid = str(user.uuid)
    db.delete(user)
    db.commit()
    return {"deleted": username, "uuid": deleted_uuid}


def _get_user_by_uuid(db: Session, user_uuid: str, request: Request) -> User:
    query = scope_user_query(select(User).where(User.uuid == user_uuid), request, User)
    user = db.execute(query).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.post("/by-uuid/{user_uuid}/faces")
def add_faces_by_uuid(
    user_uuid: str,
    request: Request,
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    user = _get_user_by_uuid(db, user_uuid, request)
    return add_faces(user.username, request, image, images, db)


@router.post("/by-uuid/{user_uuid}/password")
def set_password_by_uuid(
    user_uuid: str,
    request: Request,
    password: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    user = _get_user_by_uuid(db, user_uuid, request)
    return set_password(user.username, request, password, db)


@router.post("/by-uuid/{user_uuid}/rename")
def rename_user_by_uuid(
    user_uuid: str,
    request: Request,
    new_username: str = Form(..., min_length=3, max_length=100),
    db: Session = Depends(get_db),
):
    user = _get_user_by_uuid(db, user_uuid, request)
    return rename_user(user.username, request, new_username, db)


@router.delete("/by-uuid/{user_uuid}")
def delete_user_by_uuid(user_uuid: str, request: Request, db: Session = Depends(get_db)):
    user = _get_user_by_uuid(db, user_uuid, request)
    return delete_user(user.username, request, db)
