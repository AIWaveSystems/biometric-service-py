import logging

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..biometric_guard import check_biometric_rate
from ..biometrics.face import detector, embedder, liveness, quality
from ..config import settings
from ..database import get_db
from ..models import FaceTemplate, User
from ..ownership import api_client_id, scope_user_query
from ..schemas import (
    FaceIdentifyResponse,
    FaceLoginResponse,
    FaceRegisterResponse,
    FaceVerifyResponse,
)
from ..security import create_session_token, replay_guard

router = APIRouter(prefix="/api/face", tags=["face"])

logger = logging.getLogger("biometric.face")

ALGORITHM = "sface"
MIN_DETECTION_CONFIDENCE = 0.7
THUMB_SIZE = (64, 64)
DUP_MEAN_ABS = 1.5
BORDERLINE_MARGIN = 0.03


def _embedding_from_bytes(data: bytes, enforce_quality: bool = True) -> np.ndarray:
    img = detector.load_image(data)
    face = embedder.primary_face(img)
    if face is None:
        raise HTTPException(status_code=400, detail="No se detecto ninguna cara en la imagen")
    rect = embedder.face_rect(face, img.shape)
    if enforce_quality:
        normalized = detector.normalize_face(img, rect)
        problem = quality.check(
            quality.measure(normalized, rect, detector.raw_face(img, rect))
        )
        if problem is not None:
            raise HTTPException(status_code=400, detail=problem)
    return embedder.embed(img, face)


def _best_similarity(features: np.ndarray, templates: list[FaceTemplate]) -> float:
    best = -1.0
    for tpl in templates:
        if tpl.algorithm != ALGORITHM:
            continue
        ref = np.frombuffer(tpl.features, dtype=np.float32)
        if ref.shape != features.shape:
            continue
        best = max(best, embedder.similarity(features, ref))
    return max(best, 0.0)


def _duplicate(thumb: np.ndarray, thumbs: list[np.ndarray]) -> bool:
    probe = thumb.astype(np.int16)
    return any(
        float(np.abs(probe - other.astype(np.int16)).mean()) < DUP_MEAN_ABS
        for other in thumbs
    )


def _core_similarity(sims: list[float]) -> float:
    if not sims:
        return 0.0
    top_half = sims[: (len(sims) + 1) // 2]
    return float(np.median(top_half))


def _get_user(db: Session, username: str, request: Request | None = None) -> User:
    query = select(User).where(User.username == username)
    if request is not None:
        query = scope_user_query(query, request, User)
    user = db.execute(query).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


def _templates_or_404(user: User) -> list[FaceTemplate]:
    templates = [t for t in user.face_templates if t.algorithm == ALGORITHM]
    if not templates:
        raise HTTPException(
            status_code=404,
            detail="El usuario no tiene plantilla facial vigente. Vuelve a registrar la cara.",
        )
    return templates


@router.post("/register", response_model=FaceRegisterResponse)
def register(
    request: Request,
    username: str = Form(..., min_length=3, max_length=100),
    password: str | None = Form(default=None, min_length=6, max_length=128),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    existing_query = scope_user_query(select(User).where(User.username == username), request, User)
    existing = db.execute(existing_query).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    features = _embedding_from_bytes(image.file.read())

    if password:
        from passlib.context import CryptContext

        user = User(
            username=username,
            api_client_id=api_client_id(request),
            password_hash=CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password),
        )
    else:
        user = User(username=username, api_client_id=api_client_id(request))

    db.add(user)
    try:
        db.flush()
        db.add(FaceTemplate(user_id=user.id, algorithm=ALGORITHM, features=features.tobytes()))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    db.refresh(user)
    return FaceRegisterResponse(
        username=username,
        uuid=str(user.uuid),
        algorithm=ALGORITHM,
        message="Cara registrada correctamente",
    )


@router.post("/verify", response_model=FaceVerifyResponse)
def verify(
    request: Request,
    username: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username, request)
    templates = _templates_or_404(user)
    features = _embedding_from_bytes(image.file.read())
    best = _best_similarity(features, templates)
    verified = best >= settings.face_threshold

    return FaceVerifyResponse(
        verified=verified,
        username=username if verified else None,
        uuid=str(user.uuid) if verified else None,
        similarity=round(best, 4),
        threshold=settings.face_threshold,
    )


@router.post("/login", response_model=FaceLoginResponse)
def login(
    request: Request,
    username: str = Form(...),
    frames: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    check_biometric_rate(request, "face", username)
    user = _get_user(db, username, request)
    templates = _templates_or_404(user)
    if not frames:
        raise HTTPException(status_code=400, detail="Se requiere al menos un frame")
    if len(frames) < settings.liveness_min_faces:
        raise HTTPException(
            status_code=400,
            detail=(
                f"La captura envio muy pocos frames ({len(frames)}). "
                f"Se necesitan al menos {settings.liveness_min_faces}. Repite la captura."
            ),
        )

    payloads = [f.file.read() for f in frames]

    sequence: list[tuple[np.ndarray, np.ndarray] | None] = []
    candidates: list[tuple[int, np.ndarray, np.ndarray]] = []
    quality_problem: str | None = None
    for data in payloads:
        try:
            img = detector.load_image(data)
        except ValueError:
            sequence.append(None)
            continue
        face = embedder.primary_face(img)
        if face is None:
            sequence.append(None)
            continue
        sequence.append((img, face))
        if embedder.confidence(face) < MIN_DETECTION_CONFIDENCE:
            continue
        rect = embedder.face_rect(face, img.shape)
        normalized = detector.normalize_face(img, rect)
        problem = quality.check(
            quality.measure(normalized, rect, detector.raw_face(img, rect))
        )
        if problem is not None:
            quality_problem = problem
            continue
        candidates.append((len(sequence) - 1, img, face))

    result = liveness.analyze(
        sequence,
        min_faces=settings.liveness_min_faces,
        max_gap_ratio=settings.liveness_max_gap_ratio,
    )

    if not result["face_detected"]:
        raise HTTPException(
            status_code=400,
            detail="No se detecto la cara en suficientes frames. Asegurate de mirar a la camara.",
        )
    moved = result["moved"]
    thumbs: list[np.ndarray] = []
    features: list[np.ndarray] = []
    for idx, img, face in candidates:
        if moved[idx]:
            continue
        rect = embedder.face_rect(face, img.shape)
        thumb = cv2.resize(detector.raw_face(img, rect), THUMB_SIZE)
        if _duplicate(thumb, thumbs):
            continue
        thumbs.append(thumb)
        features.append(embedder.embed(img, face))
    if not features:
        if result["n_moved"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Demasiado movimiento durante la captura. "
                    "Quedate quieto y repite el parpadeo."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=quality_problem or "Ningun frame tiene calidad suficiente para verificar.",
        )
    if not replay_guard.check_and_register(f"face:{username}", payloads):
        raise HTTPException(
            status_code=409,
            detail="Captura repetida detectada. Vuelve a grabar el parpadeo.",
        )

    sims = sorted((_best_similarity(f, templates) for f in features), reverse=True)
    best = sims[0]
    core = _core_similarity(sims)
    blink = result["blink_detected"]
    threshold = settings.face_threshold
    match = core >= threshold
    borderline = blink and not match and core >= threshold - BORDERLINE_MARGIN
    verified = blink and match

    reason = None
    if not verified:
        if not result["stable"]:
            reason = (
                f"Solo se te detecto en {result['n_faces']} de {result['n_frames']} frames. "
                "Mira de frente a la camara sin girar la cabeza durante la captura."
            )
        elif result["n_usable"] < settings.liveness_min_faces:
            reason = (
                "Hubo demasiado movimiento durante la captura. "
                "Quedate quieto y parpadea cuando el portal te lo indique."
            )
        elif not blink:
            reason = "No se detecto parpadeo. Parpadea cuando el portal te lo indique."
        elif borderline:
            reason = (
                "El rostro queda cerca del umbral. Mejora la iluminacion, "
                "acercate a la camara y repite la captura."
            )
        else:
            reason = "El rostro no coincide con las plantillas registradas."

    logger.info(
        "face_login user=%s uuid=%s core=%.4f best=%.4f threshold=%.3f blink=%s "
        "borderline=%s usable=%d/%d verified=%s",
        username,
        user.uuid,
        core,
        best,
        threshold,
        blink,
        borderline,
        result["n_usable"],
        result["n_frames"],
        verified,
    )

    return FaceLoginResponse(
        verified=verified,
        username=username if verified else None,
        uuid=str(user.uuid) if verified else None,
        liveness_passed=blink,
        similarity=round(best, 4),
        core=round(core, 4),
        threshold=threshold,
        n_frames=result["n_frames"],
        n_faces=result["n_faces"],
        n_usable=result["n_usable"],
        n_moved=result["n_moved"],
        blink_detected=blink,
        borderline=borderline,
        access_token=create_session_token(username, "face", str(user.uuid)) if verified else None,
        expires_in=settings.session_expire_minutes * 60 if verified else None,
        reason=reason,
    )


@router.post("/identify", response_model=FaceIdentifyResponse)
def identify(request: Request, image: UploadFile = File(...), db: Session = Depends(get_db)):
    features = _embedding_from_bytes(image.file.read())

    query = (
        select(User.username, User.uuid, FaceTemplate.features)
        .join(FaceTemplate, FaceTemplate.user_id == User.id)
        .where(FaceTemplate.algorithm == ALGORITHM)
    )
    query = scope_user_query(query, request, User)
    rows = db.execute(query).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No hay usuarios registrados")

    best_user, best_uuid, best_sim = None, None, 0.0
    for row in rows:
        ref = np.frombuffer(row.features, dtype=np.float32)
        if ref.shape != features.shape:
            continue
        sim = embedder.similarity(features, ref)
        if sim > best_sim:
            best_sim, best_user, best_uuid = sim, row.username, row.uuid

    verified = best_sim >= settings.face_threshold
    return FaceIdentifyResponse(
        username=best_user if verified else None,
        uuid=str(best_uuid) if verified and best_uuid else None,
        similarity=round(best_sim, 4),
        threshold=settings.face_threshold,
    )


@router.get("/templates")
def list_templates(request: Request, db: Session = Depends(get_db)):
    query = select(User.username, FaceTemplate.algorithm, FaceTemplate.id).join(
        FaceTemplate, FaceTemplate.user_id == User.id
    )
    rows = db.execute(scope_user_query(query, request, User)).all()
    return [{"id": r.id, "username": r.username, "algorithm": r.algorithm} for r in rows]


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    tpl = db.get(FaceTemplate, template_id)
    if tpl is None or (
        api_client_id(request) is not None
        and tpl.user.api_client_id != api_client_id(request)
    ):
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    db.delete(tpl)
    db.commit()
    return {"deleted": template_id}
