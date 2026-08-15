import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..biometrics.face import detector, liveness, quality
from ..biometrics.face.lbph import extract_lbph
from ..biometrics.face.matcher import lbph_similarity
from ..config import settings
from ..database import get_db
from ..models import FaceTemplate, User
from ..schemas import (
    FaceIdentifyResponse,
    FaceLoginResponse,
    FaceRegisterResponse,
    FaceVerifyResponse,
)
from ..security import create_session_token, replay_guard

router = APIRouter(prefix="/api/face", tags=["face"])


def _features_from_bytes(data: bytes, enforce_quality: bool = True) -> np.ndarray:
    gray = detector.to_gray(detector.load_image(data))
    rect = detector.find_face_rect(gray)
    if rect is None:
        raise HTTPException(status_code=400, detail="No se detecto ninguna cara en la imagen")
    face = detector.normalize_face(gray, rect)
    if enforce_quality:
        problem = quality.check(quality.measure(face, rect))
        if problem is not None:
            raise HTTPException(status_code=400, detail=problem)
    return extract_lbph(face)


def _best_similarity(features: np.ndarray, templates: list[FaceTemplate]) -> float:
    best = 0.0
    for tpl in templates:
        ref = np.frombuffer(tpl.features, dtype=np.float32)
        if ref.shape != features.shape:
            continue
        best = max(best, lbph_similarity(features, ref))
    return best


def _get_user(db: Session, username: str) -> User:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


def _templates_or_404(user: User) -> list[FaceTemplate]:
    templates = list(user.face_templates)
    if not templates:
        raise HTTPException(status_code=404, detail="El usuario no tiene plantilla facial")
    return templates


@router.post("/register", response_model=FaceRegisterResponse)
def register(
    username: str = Form(..., min_length=3, max_length=100),
    password: str | None = Form(default=None, min_length=6, max_length=128),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    features = _features_from_bytes(image.file.read())

    if password:
        from passlib.context import CryptContext

        user = User(
            username=username,
            password_hash=CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password),
        )
    else:
        user = User(username=username)

    db.add(user)
    try:
        db.flush()
        db.add(FaceTemplate(user_id=user.id, algorithm="lbph", features=features.tobytes()))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    return FaceRegisterResponse(
        username=username,
        algorithm="lbph",
        message="Cara registrada correctamente",
    )


@router.post("/verify", response_model=FaceVerifyResponse)
def verify(
    username: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username)
    templates = _templates_or_404(user)
    features = _features_from_bytes(image.file.read())
    best = _best_similarity(features, templates)
    verified = best >= settings.face_threshold

    return FaceVerifyResponse(
        verified=verified,
        username=username if verified else None,
        similarity=round(best, 4),
        threshold=settings.face_threshold,
    )


@router.post("/login", response_model=FaceLoginResponse)
def login(
    username: str = Form(...),
    frames: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username)
    templates = _templates_or_404(user)
    if not frames:
        raise HTTPException(status_code=400, detail="Se requiere al menos un frame")

    payloads = [f.file.read() for f in frames]

    crops: list[np.ndarray | None] = []
    feature_list: list[np.ndarray] = []
    quality_problem: str | None = None
    for data in payloads:
        try:
            gray = detector.to_gray(detector.load_image(data))
        except ValueError:
            continue
        rect = detector.find_face_rect(gray)
        if rect is None:
            crops.append(None)
            continue
        x, y, w, h = rect
        crops.append(gray[y : y + h, x : x + w])
        normalized = detector.normalize_face(gray, rect)
        problem = quality.check(quality.measure(normalized, rect))
        if problem is not None:
            quality_problem = problem
            continue
        feature_list.append(extract_lbph(normalized))

    result = liveness.analyze(
        crops,
        min_faces=settings.liveness_min_faces,
        max_gap_ratio=settings.liveness_max_gap_ratio,
    )

    if not result["face_detected"]:
        raise HTTPException(
            status_code=400,
            detail="No se detecto la cara en suficientes frames. Asegurate de mirar a la camara.",
        )
    if not feature_list:
        raise HTTPException(
            status_code=400,
            detail=quality_problem or "Ningun frame tiene calidad suficiente para verificar.",
        )
    if not replay_guard.check_and_register(f"face:{username}", payloads):
        raise HTTPException(
            status_code=409,
            detail="Captura repetida detectada. Vuelve a grabar el parpadeo.",
        )

    best = max((_best_similarity(f, templates) for f in feature_list), default=0.0)
    blink = result["blink_detected"]
    match = best >= settings.face_threshold
    verified = blink and match

    reason = None
    if not verified:
        if not result["stable"]:
            reason = (
                f"Solo se te detecto en {result['n_faces']} de {result['n_frames']} frames. "
                "Mira de frente a la camara sin girar la cabeza durante la captura."
            )
        elif not blink:
            reason = "No se detecto parpadeo. Parpadea una vez durante la captura."
        else:
            reason = "El rostro no coincide con las plantillas registradas."

    return FaceLoginResponse(
        verified=verified,
        username=username if verified else None,
        liveness_passed=blink,
        similarity=round(best, 4),
        threshold=settings.face_threshold,
        n_frames=result["n_frames"],
        n_faces=result["n_faces"],
        blink_detected=blink,
        access_token=create_session_token(username, "face") if verified else None,
        expires_in=settings.session_expire_minutes * 60 if verified else None,
        reason=reason,
    )


@router.post("/identify", response_model=FaceIdentifyResponse)
def identify(image: UploadFile = File(...), db: Session = Depends(get_db)):
    features = _features_from_bytes(image.file.read())

    rows = db.execute(
        select(User.username, FaceTemplate.features).join(
            FaceTemplate, FaceTemplate.user_id == User.id
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No hay usuarios registrados")

    best_user, best_sim = None, 0.0
    for row in rows:
        ref = np.frombuffer(row.features, dtype=np.float32)
        if ref.shape != features.shape:
            continue
        sim = lbph_similarity(features, ref)
        if sim > best_sim:
            best_sim, best_user = sim, row.username

    verified = best_sim >= settings.face_threshold
    return FaceIdentifyResponse(
        username=best_user if verified else None,
        similarity=round(best_sim, 4),
        threshold=settings.face_threshold,
    )


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    rows = db.execute(
        select(User.username, FaceTemplate.algorithm, FaceTemplate.id).join(
            FaceTemplate, FaceTemplate.user_id == User.id
        )
    ).all()
    return [{"id": r.id, "username": r.username, "algorithm": r.algorithm} for r in rows]


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    tpl = db.get(FaceTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    db.delete(tpl)
    db.commit()
    return {"deleted": template_id}
