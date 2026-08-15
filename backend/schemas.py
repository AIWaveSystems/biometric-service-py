from pydantic import BaseModel, Field


class FaceRegisterResponse(BaseModel):
    username: str
    algorithm: str
    message: str


class FaceVerifyResponse(BaseModel):
    verified: bool
    username: str | None = None
    similarity: float
    threshold: float


class FaceLoginResponse(BaseModel):
    verified: bool
    username: str | None = None
    liveness_passed: bool
    similarity: float
    threshold: float
    n_frames: int
    n_faces: int
    blink_detected: bool
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    reason: str | None = None


class FaceIdentifyResponse(BaseModel):
    username: str | None
    similarity: float
    threshold: float


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None


class VoiceRegisterResponse(BaseModel):
    username: str
    algorithm: str
    n_components: int
    duration_seconds: float
    n_frames: int
    message: str


class VoiceVerifyResponse(BaseModel):
    verified: bool
    username: str | None = None
    score: float
    z_score: float
    ratio: float | None = None
    margin: float
    z_threshold: float
    ratio_threshold: float | None = None
    used_cohort: bool
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    reason: str | None = None


class UserResponse(BaseModel):
    username: str
    has_password: bool
    face_templates: list[dict]
    voice_templates: list[dict]


class FaceRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str | None = Field(default=None, min_length=6, max_length=128)
