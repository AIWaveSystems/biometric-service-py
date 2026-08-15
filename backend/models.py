from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    face_templates: Mapped[list["FaceTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    voice_templates: Mapped[list["VoiceTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class FaceTemplate(Base):
    __tablename__ = "face_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    algorithm: Mapped[str] = mapped_column(String(50))
    features: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="face_templates")


class VoiceTemplate(Base):
    __tablename__ = "voice_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    algorithm: Mapped[str] = mapped_column(String(50))
    n_components: Mapped[int] = mapped_column(Integer, default=16)
    parameters: Mapped[bytes] = mapped_column(LargeBinary)
    features: Mapped[bytes] = mapped_column(LargeBinary)
    self_score: Mapped[float] = mapped_column(Float, default=0.0)
    self_sigma: Mapped[float] = mapped_column(Float, default=1.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="voice_templates")
