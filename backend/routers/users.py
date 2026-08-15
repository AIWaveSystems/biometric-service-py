from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..biometrics.face import detector
from ..biometrics.face.lbph import extract_lbph
from ..database import get_db
from ..models import FaceTemplate, User
from ..schemas import UserResponse, VoiceRegisterResponse
from .voice import build_template

router = APIRouter(prefix="/api/users", tags=["users"])
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/register")
def register(
    username: str = Form(..., min_length=3, max_length=100),
    password: str | None = Form(default=None, min_length=6, max_length=128),
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] = File(default=[]),
    audio: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="El usuario ya existe")

    face_files = ([image] if image is not None else []) + list(images)
    if not face_files and audio is None and not password:
        raise HTTPException(
            status_code=400, detail="Se requiere al menos una biometria o una contrasena"
        )

    user = User(username=username, password_hash=pwd.hash(password) if password else None)
    db.add(user)
    db.flush()

    registered = []
    if face_files:
        n_faces = 0
        for upload in face_files:
            face = detector.detect_face(detector.load_image(upload.file.read()))
            if face is None:
                continue
            db.add(
                FaceTemplate(
                    user_id=user.id,
                    algorithm="lbph",
                    features=extract_lbph(face).tobytes(),
                )
            )
            n_faces += 1
        if n_faces == 0:
            raise HTTPException(
                status_code=400, detail="No se detecto ninguna cara en las imagenes"
            )
        registered.append(f"cara x{n_faces}")

    voice_result = None
    if audio is not None:
        template, n_components, duration, n_frames = build_template(user.id, audio.file.read())
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

    db.commit()
    return {
        "username": username,
        "registered": registered,
        "password": bool(password),
        "voice": voice_result.model_dump() if voice_result else None,
    }


@router.get("", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db)):
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    return [
        UserResponse(
            username=u.username,
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
        )
        for u in users
    ]


@router.delete("/{username}")
def delete_user(username: str, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.delete(user)
    db.commit()
    return {"deleted": username}
