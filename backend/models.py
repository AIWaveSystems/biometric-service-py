from datetime import datetime
from uuid import UUID as UUIDType
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("api_client_id", "username", name="uq_users_tenant_username"),
        Index(
            "uq_users_portal_username",
            "username",
            unique=True,
            postgresql_where=text("api_client_id IS NULL"),
            sqlite_where=text("api_client_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[UUIDType] = mapped_column(
        Uuid, unique=True, index=True, default=uuid4, nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), index=True)
    api_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_clients.id"), nullable=True, index=True
    )
    api_client: Mapped["ApiClient | None"] = relationship(back_populates="users")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    face_templates: Mapped[list["FaceTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    voice_templates: Mapped[list["VoiceTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    digit_templates: Mapped[list["VoiceDigitTemplate"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PortalUser(Base):
    __tablename__ = "portal_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[UUIDType] = mapped_column(
        Uuid, unique=True, index=True, default=uuid4, nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_bootstrap: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ApiClient(Base):
    __tablename__ = "api_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[UUIDType] = mapped_column(
        Uuid, unique=True, index=True, default=uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[str] = mapped_column(String(255), default="auth")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    users: Mapped[list[User]] = relationship(back_populates="api_client")

    @property
    def scope_list(self) -> list[str]:
        return [s.strip() for s in self.scopes.split(",") if s.strip()]

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and datetime.utcnow() >= self.expires_at

    @property
    def usable(self) -> bool:
        return self.active and not self.expired


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
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    self_score: Mapped[float] = mapped_column(Float, default=0.0)
    self_sigma: Mapped[float] = mapped_column(Float, default=1.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="voice_templates")


class VoiceChallenge(Base):
    __tablename__ = "voice_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), index=True)
    digits: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class VoiceDigitTemplate(Base):
    __tablename__ = "voice_digit_templates"
    __table_args__ = (UniqueConstraint("user_id", "digit", name="uq_voice_digit_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    digit: Mapped[str] = mapped_column(String(2), index=True)
    n_components: Mapped[int] = mapped_column(Integer, default=2)
    parameters: Mapped[bytes] = mapped_column(LargeBinary)
    cmvn: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    n_frames: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="digit_templates")
