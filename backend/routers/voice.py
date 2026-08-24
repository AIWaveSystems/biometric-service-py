import secrets

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..biometric_guard import check_biometric_rate
from ..biometrics.voice import embedder, pipeline
from ..config import settings
from ..database import get_db
from ..models import User, VoiceDigitTemplate, VoiceTemplate
from ..ownership import api_client_id, resolve_user, scope_user_query
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


def _get_user(
    db: Session, username: str, request: Request | None = None, user_uuid: str | None = None
) -> User:
    return resolve_user(db, request, username, user_uuid)


def _background_templates(
    db: Session, exclude_user_id: int, client_id: int | None = None
) -> list[VoiceTemplate]:
    query = select(VoiceTemplate).join(User, User.id == VoiceTemplate.user_id).where(
        VoiceTemplate.user_id != exclude_user_id
    )
    if client_id is not None:
        query = query.where(User.api_client_id == client_id)
    return list(db.execute(query).scalars().all())


def _unpack(template: VoiceTemplate) -> np.ndarray:
    return np.frombuffer(template.features, dtype=np.float32).reshape(-1, FEATURE_DIM)


def _cohort_features(
    db: Session, exclude_user_id: int, client_id: int | None = None
) -> list[np.ndarray]:
    return [_unpack(t) for t in _background_templates(db, exclude_user_id, client_id)]


def _background_ubm(
    db: Session, exclude_user_id: int, client_id: int | None = None
) -> tuple[object, int]:
    rows = _background_templates(db, exclude_user_id, client_id)
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


def _embedding_from_audio(data: bytes) -> bytes | None:
    if not embedder.available():
        return None
    try:
        return embedder.embed(pipeline.load_audio(data)).tobytes()
    except (ValueError, RuntimeError):
        return None


def _stored_embedding(blob: bytes | None) -> np.ndarray | None:
    if not blob or len(blob) != embedder.EMBEDDING_DIM * 4:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def _enrolled_embeddings(
    db: Session, exclude_user_id: int | None, client_id: int | None = None
) -> list[tuple[str, np.ndarray]]:
    query = (
        select(User.username, VoiceTemplate.embedding)
        .join(VoiceTemplate, VoiceTemplate.user_id == User.id)
        .where(VoiceTemplate.embedding.is_not(None))
    )
    if exclude_user_id is not None:
        query = query.where(VoiceTemplate.user_id != exclude_user_id)
    if client_id is not None:
        query = query.where(User.api_client_id == client_id)
    salida = []
    for nombre, blob in db.execute(query).all():
        vector = _stored_embedding(blob)
        if vector is not None:
            salida.append((nombre, vector))
    return salida


def find_duplicate_voice(
    db: Session,
    embedding: bytes | None,
    exclude_user_id: int | None,
    client_id: int | None = None,
) -> tuple[str, float] | None:
    probe = _stored_embedding(embedding)
    if probe is None:
        return None
    mejor: tuple[str, float] | None = None
    for nombre, referencia in _enrolled_embeddings(db, exclude_user_id, client_id):
        score = embedder.similarity(probe, referencia)
        if mejor is None or score > mejor[1]:
            mejor = (nombre, score)
    if mejor is None or mejor[1] < settings.voice_duplicate_threshold:
        return None
    return mejor


def build_template(user_id: int, data: bytes) -> tuple[VoiceTemplate, int, float, int]:
    feat, duration = _features_from_upload(data)
    model, self_score, self_sigma = pipeline.enroll(feat)
    template = VoiceTemplate(
        user_id=user_id,
        embedding=_embedding_from_audio(data),
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
    request: Request,
    username: str = Form(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username, request)
    template, n_components, duration, n_frames = build_template(user.id, audio.file.read())

    duplicado = find_duplicate_voice(db, template.embedding, user.id, api_client_id(request))
    if duplicado is not None and settings.voice_reject_duplicates:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Esta voz ya esta matriculada como '{duplicado[0]}' "
                f"(similitud {duplicado[1]:.3f}, umbral {settings.voice_duplicate_threshold}). "
                "Matricular la misma voz en dos cuentas hace que una sola grabacion abra "
                "las dos. Si de verdad son personas distintas, sube el audio correcto o "
                "revisa la matricula de esa otra cuenta."
            ),
        )

    for old in user.voice_templates:
        db.delete(old)
    db.add(template)
    db.commit()

    mensaje = "Voz registrada correctamente"
    if duplicado is not None:
        mensaje = (
            f"Voz registrada, PERO se parece a la de '{duplicado[0]}' "
            f"(similitud {duplicado[1]:.3f}). Una sola grabacion podria abrir ambas cuentas."
        )

    return VoiceRegisterResponse(
        username=username,
        uuid=str(user.uuid),
        algorithm="mfcc-gmm",
        n_components=n_components,
        duration_seconds=round(duration, 2),
        n_frames=n_frames,
        message=mensaje,
        duplicate_of=None if duplicado is None else duplicado[0],
        duplicate_similarity=None if duplicado is None else round(duplicado[1], 4),
    )


@router.post("/verify", response_model=VoiceVerifyResponse)
def verify(
    request: Request,
    username: str = Form(...),
    user_uuid: str | None = Form(default=None),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    check_biometric_rate(request, "voice", username)
    user = _get_user(db, username, request, user_uuid)
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

    reference = _stored_embedding(tpl.embedding)
    if reference is not None and embedder.available():
        try:
            probe = embedder.embed(pipeline.load_audio(data))
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        score = embedder.similarity(probe, reference)
        verified = score >= settings.voice_embedding_threshold
        return VoiceVerifyResponse(
            verified=verified,
            username=username if verified else None,
            uuid=str(user.uuid) if verified else None,
            score=round(score, 4),
            z_score=0.0,
            ratio=round(score, 4),
            margin=round(score, 4),
            z_threshold=settings.voice_embedding_threshold,
            ratio_threshold=settings.voice_embedding_threshold,
            used_cohort=False,
            scoring="embedding",
            n_background_speakers=0,
            access_token=create_session_token(username, "voice", str(user.uuid)) if verified else None,
            expires_in=settings.session_expire_minutes * 60 if verified else None,
            reason=None if verified else "La voz no coincide con la plantilla registrada.",
        )

    ubm, n_background = _background_ubm(db, tpl.user_id, api_client_id(request))

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
    cohort = pipeline.voice_service.cohort_gmm(
        _cohort_features(db, tpl.user_id, api_client_id(request))
    )
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
    db: Session,
    tpl: VoiceTemplate,
    feat: np.ndarray,
    raw: bytes | None = None,
    client_id: int | None = None,
) -> tuple[bool, float, str, int]:
    referencia = _stored_embedding(tpl.embedding)
    if referencia is not None and embedder.available() and raw is not None:
        try:
            probe = embedder.embed(pipeline.load_audio(raw))
        except (ValueError, RuntimeError):
            probe = None
        if probe is not None:
            score = embedder.similarity(probe, referencia)
            return score >= settings.voice_embedding_threshold, score, "embedding", 0

    ubm, n_background = _background_ubm(db, tpl.user_id, client_id)
    if ubm is not None:
        target = ubm.map_adapt(_unpack(tpl), relevance=pipeline.MAP_RELEVANCE)
        llr = pipeline.voice_service.verify_ubm(target, ubm, feat)
        return llr >= settings.voice_llr_threshold, llr, "ubm-map", n_background

    target = pipeline.deserialize_gmm(tpl.parameters)
    cohort = pipeline.voice_service.cohort_gmm(_cohort_features(db, tpl.user_id, client_id))
    _, z, ratio, _ = pipeline.voice_service.verify(
        target, tpl.self_score, tpl.self_sigma, cohort, feat
    )
    passed = z >= settings.voice_z_threshold and (
        ratio is None or ratio >= settings.voice_ratio_threshold
    )
    return passed, z, "gmm-z", n_background


def _digit_models(user: User) -> tuple[dict[str, object], tuple | None]:
    modelos = {t.digit: pipeline.deserialize_gmm(t.parameters) for t in user.digit_templates}
    guardada = next((t.cmvn for t in user.digit_templates if t.cmvn), None)
    return modelos, None if guardada is None else pipeline.unpack_stats(guardada)


@router.post("/digits/enroll", response_model=VoiceDigitEnrollResponse)
def enroll_digits(
    request: Request,
    username: str = Form(...),
    digits: str = Form(",".join(pipeline.DIGITS)),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = _get_user(db, username, request)
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
def digit_status(username: str, request: Request, db: Session = Depends(get_db)):
    user = _get_user(db, username, request)
    enrolled = sorted(t.digit for t in user.digit_templates)
    cmvn_ok = bool(user.digit_templates) and all(t.cmvn for t in user.digit_templates)
    needed = settings.voice_challenge_digits + 1
    return {
        "username": username,
        "enrolled": enrolled,
        "missing": [d for d in pipeline.DIGITS if d not in enrolled],
        "cmvn_ok": cmvn_ok,
        "ready": len(enrolled) >= needed and cmvn_ok,
        "needed": needed,
    }


@router.get("/system")
def voice_system(request: Request, db: Session = Depends(get_db)):
    voice_users_query = select(func.count(func.distinct(VoiceTemplate.user_id))).join(
        User, User.id == VoiceTemplate.user_id
    )
    embedding_query = voice_users_query.where(
        func.length(VoiceTemplate.embedding) == embedder.EMBEDDING_DIM * 4
    )
    n_voice_users = db.execute(
        scope_user_query(voice_users_query, request, User)
    ).scalar_one()
    n_embedding = db.execute(scope_user_query(embedding_query, request, User)).scalar_one()
    modelo = embedder.available()
    ubm_min_users = MIN_BACKGROUND_SPEAKERS + 1
    sin_embedding = n_voice_users - n_embedding

    if modelo and n_embedding == n_voice_users and n_voice_users > 0:
        scoring_active = "embedding"
    elif n_embedding > 0 and modelo:
        scoring_active = "mixto"
    elif n_voice_users >= ubm_min_users:
        scoring_active = "ubm-map"
    else:
        scoring_active = "gmm-z"

    return {
        "embedding_model": modelo,
        "embedding_threshold": settings.voice_embedding_threshold,
        "voice_users": n_voice_users,
        "users_with_embedding": n_embedding,
        "users_without_embedding": sin_embedding,
        "scoring_active": scoring_active,
        "needs_more_speakers": scoring_active in ("ubm-map", "gmm-z", "mixto"),
        "ubm_min_users": ubm_min_users,
        "ubm_ready": n_voice_users >= ubm_min_users,
        "challenge_digits": settings.voice_challenge_digits,
        "challenge_min_enrolled": settings.voice_challenge_digits + 1,
    }


@router.delete("/digits/{username}")
def delete_digits(username: str, request: Request, db: Session = Depends(get_db)):
    user = _get_user(db, username, request)
    removed = len(user.digit_templates)
    for template in list(user.digit_templates):
        db.delete(template)
    db.commit()
    return {"username": username, "deleted": removed}


@router.post("/challenge", response_model=VoiceChallengeResponse)
def create_challenge(
    request: Request,
    username: str = Form(...),
    user_uuid: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    check_biometric_rate(request, "voice-challenge", username)
    user = _get_user(db, username, request, user_uuid)
    if not user.voice_templates:
        raise HTTPException(status_code=404, detail="El usuario no tiene plantilla de voz")

    enrolled = sorted(t.digit for t in user.digit_templates)
    needed = settings.voice_challenge_digits
    min_enrolled = needed + 1
    if len(enrolled) < min_enrolled:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El usuario tiene {len(enrolled)} digitos matriculados y hacen falta "
                f"al menos {min_enrolled}. Usa POST /api/voice/digits/enroll."
            ),
        )
    if not all(t.cmvn for t in user.digit_templates):
        raise HTTPException(
            status_code=409,
            detail=(
                "La matricula de digitos es antigua o incompleta. "
                "Vuelve a matricular los 10 digitos desde el portal."
            ),
        )

    rng = secrets.SystemRandom()
    chosen = tuple(rng.sample(enrolled, needed))
    token, ttl = challenge_store.issue(db, username, chosen)

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
    request: Request,
    username: str = Form(...),
    user_uuid: str | None = Form(default=None),
    challenge_id: str = Form(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    check_biometric_rate(request, "voice-challenge", username)
    expected = challenge_store.consume(db, challenge_id, username)
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Desafio invalido, caducado o ya usado. Pide uno nuevo.",
        )

    user = _get_user(db, username, request, user_uuid)
    tpl = (user.voice_templates or [None])[0]
    if tpl is None:
        raise HTTPException(status_code=404, detail="El usuario no tiene plantilla de voz")

    models, stats = _digit_models(user)
    if len(models) < 2:
        raise HTTPException(status_code=409, detail="El usuario no tiene digitos matriculados")
    if stats is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "La matricula de digitos no tiene normalizacion guardada. "
                "Vuelve a matricular los 10 digitos desde el portal."
            ),
        )

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

    identity_ok, score, scoring, n_background = _score_identity(
        db, tpl, feat, data, api_client_id(request)
    )

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


@router.post("/identify")
def identify(request: Request, audio: UploadFile = File(...), db: Session = Depends(get_db)):
    if not embedder.available():
        raise HTTPException(status_code=503, detail="El modelo de locutor no esta descargado")
    data = audio.file.read()
    try:
        probe = embedder.embed(pipeline.load_audio(data))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    puntuados = sorted(
        (
            (nombre, embedder.similarity(probe, ref))
            for nombre, ref in _enrolled_embeddings(db, None, api_client_id(request))
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )
    aceptados = [n for n, v in puntuados if v >= settings.voice_embedding_threshold]
    mejor = puntuados[0] if puntuados else None
    return {
        "username": mejor[0] if mejor and mejor[1] >= settings.voice_embedding_threshold else None,
        "similarity": round(mejor[1], 4) if mejor else None,
        "threshold": settings.voice_embedding_threshold,
        "matches": aceptados,
        "ambiguous": len(aceptados) > 1,
        "ranking": [{"username": n, "similarity": round(v, 4)} for n, v in puntuados[:5]],
    }


@router.get("/templates")
def list_templates(request: Request, db: Session = Depends(get_db)):
    query = (
        select(
            User.username,
            VoiceTemplate.id,
            VoiceTemplate.n_components,
            VoiceTemplate.duration_seconds,
        ).join(VoiceTemplate, VoiceTemplate.user_id == User.id)
    )
    rows = db.execute(scope_user_query(query, request, User)).all()
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
def delete_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    tpl = db.get(VoiceTemplate, template_id)
    if tpl is None or (
        api_client_id(request) is not None
        and tpl.user.api_client_id != api_client_id(request)
    ):
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    db.delete(tpl)
    db.commit()
    return {"deleted": template_id}
