from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    session_expire_minutes: int = 15

    face_threshold: float = 0.70
    voice_z_threshold: float = -2.5
    voice_llr_threshold: float = 0.4
    voice_ratio_threshold: float = -3.0

    liveness_min_faces: int = 6
    liveness_max_gap_ratio: float = 0.4

    replay_window_seconds: int = 300
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60

    cors_origins: str = ""

    portal_user: str = ""
    portal_password: str = ""
    docs_user: str = ""
    docs_password: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def docs_user_resolved(self) -> str:
        return self.docs_user or self.portal_user

    @property
    def docs_password_resolved(self) -> str:
        return self.docs_password or self.portal_password

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
