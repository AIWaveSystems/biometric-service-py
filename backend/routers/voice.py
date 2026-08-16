import secrets

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..biometrics.voice import pipeline
from ..config import settings
from ..database import get_db
from ..models import User, VoiceDigitTemplate, VoiceTemplate
from ..schemas import (
    VoiceChallengeResponse,
    VoiceChallengeVerifyResponse,
    VoiceDigitEnrollResponse,
    VoiceRegisterResponse,
    VoiceVerifyResponse,
)
from ..security import challenge_store, create_session_token, replay_guard

router = APIRouter(prefix="/api/voice", tags=["voice"])

FEATURE_DIM = 39
MIN_BACKGROUND_SPEAKERS = 2


def _get_user(db: Session, username: str) -> User:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


def _background_templates(db: Session, exclude_user_id: int) -> list[VoiceTemplate]:
    return list(
        db.execute(select(VoiceTemplate).where(VoiceTemplate.user_id != exclude_user_id))
        .scalars()
        .all()
    )


def _unpack(template: VoiceTemplate) -> np.ndarray:
    return np.frombuffer(template.features, dtype=np.float32).reshape(-1, FEATURE_DIM)


def _cohort_features(db: Session, exclude_user_id: int) -> list[np.ndarray]:
    return [_unpack(t) for t in _background_templates(db, exclude_user_id)]


def _background_ubm(db: Session, exclude_user_id: int) -> tuple[object, int]:
    rows = _background_templates(db, exclude_user_id)
    speakers = {t.user_id for t in rows}
    if len(speakers) < MIN_BACKGROUND_SPEAKERS:
        return None, len(speakers)
    key = tuple(sorted((t.id, len(t.features)) for t in rows))
    return pipeline.ubm_cache.get(key, [_unpack(t) for t in rows]), len(speakers)


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
        uuid=str(user.uuid),
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
    feat, _ = _features_from_upload(data)

    if not replay_guard.check_and_register(f"voice:{username}", [data]):
        raise HTTPException(
            status_code=409,
            detail="Grabacion repetida detectada. Vuelve a grabar tu voz.",
        )

    ubm, n_background = _background_ubm(db, tpl.user_id)

    if ubm is not None:
        target = ubm.map_adapt(_unpack(tpl), relevance=pipeline.MAP_RELEVANCE)
        llr = pipeline.voice_service.verify_ubm(target, ubm, feat)
        verified = llr >= settings.voice_llr_threshold
        reason = None if verified else "La voz no coincide con la plantilla registrada."
        return VoiceVerifyResponse(
            verified=verified,
            username=username if verified else None,
            uuid=str(user.uuid) if verified else None,
            score=round(llr, 3),
            z_score=0.0,
            ratio=round(llr, 3),
            margin=round(llr, 3),
            z_threshold=settings.voice_llr_threshold,
            ratio_threshold=settings.voice_llr_threshold,
            used_cohort=True,
            scoring="ubm-map",
            n_background_speakers=n_background,
            access_token=create_session_token(username, "voice", str(user.uuid)) if verified else None,
            expires_in=settings.session_expire_minutes * 60 if verified else None,
            reason=reason,
        )

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
        uuid=str(user.uuid) if verified else None,
        score=round(margin, 3),
        z_score=round(z, 3),
        ratio=round(ratio, 3) if ratio is not None else None,
        margin=round(margin, 3),
        z_threshold=settings.voice_z_threshold,
        ratio_threshold=settings.voice_ratio_threshold if used_cohort else None,
        used_cohort=used_cohort,
        scoring="gmm-z",
        n_background_speakers=n_background,
        access_token=create_session_token(username, "voice", str(user.uuid)) if verified else None,
        expires_in=settings.session_expire_minutes * 60 if verified else None,
        reason=reason,
    )


def _score_identity(
    db: Session, tpl: VoiceTemplate, feat: np.ndarray
) -> tuple[bool, float, str, int]:
    """Decide si la voz es del titular, con la misma logica que /verify."""
    ubm, n_background = _background_ubm(db, tpl.user_id)
    if ubm is not None:
        target = ubm.map_adapt(_unpack(tpl), relevance=pipeline.MAP_RELEVANCE)
        llr = pipeline.voice_service.verify_ubm(target, ubm, feat)
        return llr >= settings.voice_llr_threshold, llr, "ubm-map", n_background

    target = pipeline.deserialize_gmm(tpl.parameters)
    cohort = pipeline.voice_service.cohort_gmm(_cohort_features(db, tpl.user_id))
    _, z, ratio, _ = pipeline.voice_service.verify(
        target, tpl.self_score, tpl.self_sigma, cohort, feat
    )
    passed = z >= settings.voice_z_threshold and (
        ratio is None or ratio >= settings.voice_ratio_threshold
    )
    return passed, z, "gmm-z", n_background


def _digit_models(user: User) -> tuple[dict[str, object], tuple | None]:
    """Modelos por digito y la normalizacion con la que se matricularon.

    Sin esa normalizacion el desafio se mediria en otro espacio que la matricula.
    Las matriculas anteriores a esta version no la tienen guardada (cmvn=None) y
    caen al comportamiento antiguo, que funciona pero con mas error.
    """
    modelos = {t.digit: pipeline.deserialize_gmm(t.parameters) for t in user.digit_templates}
    guardada = next((t.cmvn for t in user.digit_templates if t.cmvn), None)
    return modelos, None if guardada is None else pipeline.unpack_stats(guardada)


@router.post("/digits/enroll", response_model=VoiceDigitEnrollResponse)
def enroll_digits(
    username: str = Form(...),
    digits: str = Form(",".join(pipeline.DIGITS)),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Matricula la pronunciacion de cada digito a partir de una sola toma.

    El usuario dice los digitos indicados en ese orden, con una pausa entre
    ellos; el troceo por energia debe encontrar exactamente tantas locuciones
    como digitos, o la toma se rechaza sin tocar lo ya matriculado.
    """
    user = _get_user(db, username)
    wanted = [d.strip() for d in digits.split(",") if d.strip()]
    if not wanted or any(d not in pipeline.DIGITS for d in wanted):
        raise HTTPException(status_code=400, detail="Lista de digitos invalida (usa 0..9)")
    if len(set(wanted)) != len(wanted):
        raise HTTPException(status_code=400, detail="La lista de digitos tiene repetidos")

    try:
        x = pipeline.load_audio(audio.file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    duration = len(x) / pipeline.SAMPLE_RATE
    segments, stats = pipeline.split_utterance(x)
    if len(segments) != len(wanted):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Se esperaban {len(wanted)} digitos y se detectaron {len(segments)} "
                "locuciones. Repite la grabacion dejando una pausa clara entre digitos "
                "y sin ruido de fondo."
            ),
        )

    short = [
        wanted[i] for i, seg in enumerate(segments) if len(seg) < pipeline.DIGIT_MIN_FRAMES
    ]
    if short:
        raise HTTPException(
            status_code=400,
            detail=f"Digitos demasiado breves: {', '.join(short)}. Alargalos un poco.",
        )

    built = []
    frames_per_digit: dict[str, int] = {}
    for digit, seg in zip(wanted, segments):
        model = pipeline.fit_digit_gmm(seg)
        built.append(
            VoiceDigitTemplate(
                user_id=user.id,
                digit=digit,
                n_components=model.n_components,
                parameters=pipeline.serialize_gmm(model),
                cmvn=pipeline.pack_stats(stats),
                n_frames=len(seg),
            )
        )
        frames_per_digit[digit] = len(seg)

    for old in list(user.digit_templates):
        if old.digit in frames_per_digit:
            db.delete(old)
    db.flush()
    for template in built:
        db.add(template)
    db.commit()

    return VoiceDigitEnrollResponse(
        username=username,
        uuid=str(user.uuid),
        digits=wanted,
        n_segments=len(segments),
        frames_per_digit=frames_per_digit,
        duration_seconds=round(duration, 2),
        message="Digitos matriculados correctamente",
    )


@router.get("/digits/{username}")
def digit_status(username: str, db: Session = Depends(get_db)):
    user = _get_user(db, username)
    enrolled = sorted(t.digit for t in user.digit_templates)
    return {
        "username": username,
        "enrolled": enrolled,
        "missing": [d for d in pipeline.DIGITS if d not in enrolled],
        "ready": len(enrolled) >= settings.voice_challenge_digits + 1,
    }


@router.delete("/digits/{username}")
def delete_digits(username: str, db: Session = Depends(get_db)):
    user = _get_user(db, username)
    removed = len(user.digit_templates)
    for template in list(user.digit_templates):
        db.delete(template)
    db.commit()
    return {"username": username, "deleted": removed}


@router.post("/challenge", response_model=VoiceChallengeResponse)
def create_challenge(username: str = Form(...), db: Session = Depends(get_db)):
    user = _get_user(db, username)
    if not user.voice_templates:
        raise HTTPException(status_code=404, detail="El usuario no tiene plantilla de voz")

    enrolled = sorted(t.digit for t in user.digit_templates)
    needed = settings.voice_challenge_digits
    if len(enrolled) < needed + 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El usuario tiene {len(enrolled)} digitos matriculados y hacen falta "
                f"al menos {needed + 1}. Usa POST /api/voice/digits/enroll."
            ),
        )

    rng = secrets.SystemRandom()
    chosen = tuple(rng.sample(enrolled, needed))
    token, ttl = challenge_store.issue(username, chosen)

    return VoiceChallengeResponse(
        challenge_id=token,
        username=username,
        digits=list(chosen),
        expires_in=ttl,
        instructions=(
            "Di en voz alta estos digitos en este orden, con una pausa breve entre "
            "cada uno, y envia la grabacion a /api/voice/challenge/verify."
        ),
    )


@router.post("/challenge/verify", response_model=VoiceChallengeVerifyResponse)
def verify_challenge(
    username: str = Form(...),
    challenge_id: str = Form(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Verifica QUIEN habla y QUE dijo contra un desafio de un solo uso.

    Una grabacion previa no puede responder digitos que el servidor eligio
    despues de grabarla, que es justamente lo que el analisis pasivo del canal
    no consiguio distinguir.
    """
    expected = challenge_store.consume(challenge_id, username)
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Desafio invalido, caducado o ya usado. Pide uno nuevo.",
        )

    user = _get_user(db, username)
    tpl = (user.voice_templates or [None])[0]
    if tpl is None:
        raise HTTPException(status_code=404, detail="El usuario no tiene plantilla de voz")

    models, stats = _digit_models(user)
    if len(models) < 2:
        raise HTTPException(status_code=409, detail="El usuario no tiene digitos matriculados")

    data = audio.file.read()
    if not replay_guard.check_and_register(f"voice-challenge:{username}", [data]):
        raise HTTPException(
            status_code=409,
            detail="Grabacion repetida detectada. Vuelve a grabar tu voz.",
        )

    feat, _ = _features_from_upload(data)

    try:
        x = pipeline.load_audio(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    segments, _ = pipeline.split_utterance(x, stats)

    identity_ok, score, scoring, n_background = _score_identity(db, tpl, feat)

    recognised: list[str] = []
    margins: list[float] = []
    for seg in segments:
        if len(seg) < pipeline.DIGIT_MIN_FRAMES:
            recognised.append("?")
            margins.append(0.0)
            continue
        label, margin = pipeline.classify_digit(seg, models)
        recognised.append(label)
        margins.append(margin)

    min_margin = min(margins) if margins else None
    if len(segments) != len(expected):
        content_ok = False
        n_errors = len(expected)
    else:
        n_errors = sum(1 for got, want in zip(recognised, expected) if got != want)
        content_ok = (
            n_errors <= settings.voice_challenge_max_errors
            and min_margin is not None
            and min_margin >= settings.voice_challenge_min_margin
        )

    verified = identity_ok and content_ok

    reason = None
    if not verified:
        if len(segments) != len(expected):
            reason = (
                f"Se esperaban {len(expected)} digitos y se detectaron {len(segments)}. "
                "Repite con una pausa clara entre cada digito."
            )
        elif not content_ok:
            reason = "Los digitos pronunciados no coinciden con los del desafio."
        else:
            reason = "La voz no coincide con la plantilla registrada."

    return VoiceChallengeVerifyResponse(
        verified=verified,
        username=username if verified else None,
        uuid=str(user.uuid) if verified else None,
        identity_ok=identity_ok,
        content_ok=content_ok,
        expected=list(expected),
        recognised=recognised,
        n_segments=len(segments),
        n_errors=n_errors,
        min_margin=round(min_margin, 3) if min_margin is not None else None,
        score=round(score, 3),
        scoring=scoring,
        n_background_speakers=n_background,
        access_token=(
            create_session_token(username, "voice-challenge", str(user.uuid))
            if verified
            else None
        ),
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
