from typing import Literal

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=25, ge=1, le=100)
    search: str | None = Field(default=None, max_length=100)
    sort_by: str = Field(default="username", max_length=50)
    sort_dir: Literal["asc", "desc"] = "asc"


class FaceRegisterResponse(BaseModel):
    username: str
    uuid: str
    algorithm: str
    message: str


class FaceVerifyResponse(BaseModel):
    verified: bool
    username: str | None = None
    uuid: str | None = None
    similarity: float
    threshold: float


class FaceLoginResponse(BaseModel):
    verified: bool
    username: str | None = None
    uuid: str | None = None
    liveness_passed: bool
    similarity: float
    core: float
    threshold: float
    n_frames: int
    n_faces: int
    n_usable: int = 0
    n_moved: int = 0
    blink_detected: bool
    borderline: bool = False
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    reason: str | None = None


class FaceIdentifyResponse(BaseModel):
    username: str | None
    uuid: str | None = None
    similarity: float
    threshold: float


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None


class VoiceRegisterResponse(BaseModel):
    username: str
    uuid: str | None = None
    algorithm: str
    n_components: int
    duration_seconds: float
    n_frames: int
    message: str
    duplicate_of: str | None = None
    duplicate_similarity: float | None = None


class VoiceVerifyResponse(BaseModel):
    verified: bool
    username: str | None = None
    uuid: str | None = None
    score: float
    z_score: float
    ratio: float | None = None
    margin: float
    z_threshold: float
    ratio_threshold: float | None = None
    used_cohort: bool
    scoring: str = "gmm-z"
    n_background_speakers: int = 0
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    reason: str | None = None


class VoiceDigitEnrollResponse(BaseModel):
    username: str
    uuid: str | None = None
    digits: list[str]
    n_segments: int
    frames_per_digit: dict[str, int]
    duration_seconds: float
    message: str


class VoiceChallengeResponse(BaseModel):
    challenge_id: str
    username: str
    digits: list[str]
    expires_in: int
    instructions: str


class VoiceChallengeVerifyResponse(BaseModel):
    verified: bool
    username: str | None = None
    uuid: str | None = None
    identity_ok: bool
    content_ok: bool
    expected: list[str]
    recognised: list[str]
    n_segments: int
    n_errors: int
    min_margin: float | None = None
    score: float | None = None
    scoring: str = "gmm-z"
    n_background_speakers: int = 0
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    reason: str | None = None


class UserResponse(BaseModel):
    username: str
    uuid: str
    has_password: bool
    face_templates: list[dict]
    voice_templates: list[dict]
    digits: list[str] = []
    digits_challenge_ready: bool = False
    digits_cmvn_ok: bool = False
    owner: dict | None = None


class FaceRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str | None = Field(default=None, min_length=6, max_length=128)
