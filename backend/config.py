from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    session_expire_minutes: int = 15

    face_threshold: float = 0.363
    voice_z_threshold: float = -2.5
    voice_llr_threshold: float = 1.2
    voice_embedding_threshold: float = 0.35
    voice_duplicate_threshold: float = 0.35
    voice_reject_duplicates: bool = True
    voice_ratio_threshold: float = -3.0

    voice_challenge_digits: int = 4
    voice_challenge_ttl_seconds: int = 60
    voice_challenge_min_margin: float = 0.0
    voice_challenge_max_errors: int = 0

    liveness_min_faces: int = 6
    liveness_max_gap_ratio: float = 0.4

    replay_window_seconds: int = 300
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60

    cors_origins: str = ""

    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_recycle: int = 1800

    api_key_pepper: str = ""
    api_key_default_days: int = 365

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
