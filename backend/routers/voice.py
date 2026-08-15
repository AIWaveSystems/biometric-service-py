import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..biometrics.voice import pipeline
from ..config import settings
from ..database import get_db
from ..models import User, VoiceTemplate
from ..schemas import VoiceRegisterResponse, VoiceVerifyResponse
from ..security import create_session_token, replay_guard

router = APIRouter(prefix="/api/voice", tags=["voice"])

FEATURE_DIM = 39


def _get_user(db: Session, username: str) -> User:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


def _cohort_features(db: Session, exclude_user_id: int) -> list[np.ndarray]:
    rows = (
        db.execute(select(VoiceTemplate).where(VoiceTemplate.user_id != exclude_user_id))
        .scalars()
        .all()
    )
    return [np.frombuffer(t.features, dtype=np.float32).reshape(-1, FEATURE_DIM) for t in rows]


def _features_from_upload(data: bytes) -> tuple[np.ndarray, float]:
    try:
        return pipeline.extract_features(pipeline.load_audio(data))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def build_template(user_id: int, data: bytes) -> tuple[VoiceTemplate, int, float, int]:
    feat, duration = _features_from_upload(data)
    model, self_score, self_sigma = pipeline.enroll(feat)
    template = VoiceTemplate(
        user_id=user_id,
        algorithm="mfcc-gmm",
        n_components=model.n_components,
        parameters=pipeline.serialize_gmm(model),
        features=feat.astype(np.float32).tobytes(),
        self_score=self_score,
        self_sigma=self_sigma,
        duration_seconds=round(duration, 2),
    )
    return template, model.n_components, duration, len(feat)


@router.post("/register", response_model=VoiceRegisterResponse)
def register(
    username: str = Form(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username)
    template, n_components, duration, n_frames = build_template(user.id, audio.file.read())

    for old in user.voice_templates:
        db.delete(old)
    db.add(template)
    db.commit()

    return VoiceRegisterResponse(
        username=username,
        algorithm="mfcc-gmm",
        n_components=n_components,
        duration_seconds=round(duration, 2),
        n_frames=n_frames,
        message="Voz registrada correctamente",
    )


@router.post("/verify", response_model=VoiceVerifyResponse)
def verify(
    username: str = Form(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username)
    tpl = (user.voice_templates or [None])[0]
    if tpl is None:
        raise HTTPException(status_code=404, detail="El usuario no tiene plantilla de voz")

    data = audio.file.read()
    if not replay_guard.check_and_register(f"voice:{username}", [data]):
        raise HTTPException(
            status_code=409,
            detail="Grabacion repetida detectada. Vuelve a grabar tu voz.",
        )

    feat, _ = _features_from_upload(data)

    target = pipeline.deserialize_gmm(tpl.parameters)
    cohort = pipeline.voice_service.cohort_gmm(_cohort_features(db, tpl.user_id))
    margin, z, ratio, used_cohort = pipeline.voice_service.verify(
        target, tpl.self_score, tpl.self_sigma, cohort, feat
    )

    passed_z = z >= settings.voice_z_threshold
    passed_ratio = ratio is None or ratio >= settings.voice_ratio_threshold
    verified = passed_z and passed_ratio

    reason = None
    if not verified:
        if not passed_z:
            reason = "La voz no coincide con la plantilla registrada."
        else:
            reason = "La voz se parece mas a otro usuario registrado que al tuyo."

    return VoiceVerifyResponse(
        verified=verified,
        username=username if verified else None,
        score=round(margin, 3),
        z_score=round(z, 3),
        ratio=round(ratio, 3) if ratio is not None else None,
        margin=round(margin, 3),
        z_threshold=settings.voice_z_threshold,
        ratio_threshold=settings.voice_ratio_threshold if used_cohort else None,
        used_cohort=used_cohort,
        access_token=create_session_token(username, "voice") if verified else None,
        expires_in=settings.session_expire_minutes * 60 if verified else None,
        reason=reason,
    )


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            User.username,
            VoiceTemplate.id,
            VoiceTemplate.n_components,
            VoiceTemplate.duration_seconds,
        ).join(VoiceTemplate, VoiceTemplate.user_id == User.id)
    ).all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "n_components": r.n_components,
            "duration_seconds": r.duration_seconds,
        }
        for r in rows
    ]


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    tpl = db.get(VoiceTemplate, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    db.delete(tpl)
    db.commit()
    return {"deleted": template_id}
