import threading
from pathlib import Path

import cv2
import numpy as np

MODEL_DIR = Path(__file__).resolve().parent / "models"
DETECTOR_PATH = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_PATH = MODEL_DIR / "face_recognition_sface_2021dec.onnx"

DETECT_SCORE_THRESHOLD = 0.6
DETECT_NMS_THRESHOLD = 0.3
DETECT_TOP_K = 5000
EMBEDDING_DIM = 128

_local = threading.local()


class ModelsUnavailable(RuntimeError):
    pass


def _require_models() -> None:
    missing = [p.name for p in (DETECTOR_PATH, RECOGNIZER_PATH) if not p.exists()]
    if missing:
        raise ModelsUnavailable(
            "Faltan los modelos ONNX en backend/biometrics/face/models: "
            + ", ".join(missing)
            + ". Ejecuta: python scripts/fetch_models.py"
        )


def _detector() -> cv2.FaceDetectorYN:
    det = getattr(_local, "detector", None)
    if det is None:
        _require_models()
        det = cv2.FaceDetectorYN.create(
            str(DETECTOR_PATH),
            "",
            (320, 320),
            DETECT_SCORE_THRESHOLD,
            DETECT_NMS_THRESHOLD,
            DETECT_TOP_K,
        )
        _local.detector = det
    return det


def _recognizer() -> cv2.FaceRecognizerSF:
    rec = getattr(_local, "recognizer", None)
    if rec is None:
        _require_models()
        rec = cv2.FaceRecognizerSF.create(str(RECOGNIZER_PATH), "")
        _local.recognizer = rec
    return rec


def available() -> bool:
    return DETECTOR_PATH.exists() and RECOGNIZER_PATH.exists()


def detect_faces(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    height, width = img.shape[:2]
    det = _detector()
    det.setInputSize((width, height))
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return np.empty((0, 15), dtype=np.float32)
    return np.asarray(sorted(faces, key=lambda f: -f[2] * f[3]), dtype=np.float32)


def primary_face(img: np.ndarray) -> np.ndarray | None:
    faces = detect_faces(img)
    return None if len(faces) == 0 else faces[0]


def face_rect(face: np.ndarray, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    x, y, w, h = (int(round(v)) for v in face[:4])
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    return x, y, max(1, min(w, width - x)), max(1, min(h, height - y))


def confidence(face: np.ndarray) -> float:
    return float(face[14])


def embed(img: np.ndarray, face: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    rec = _recognizer()
    aligned = rec.alignCrop(img, face)
    vector = np.asarray(rec.feature(aligned), dtype=np.float32).flatten()
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError("Embedding facial degenerado")
    return (vector / norm).astype(np.float32)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.clip(np.dot(a, b), -1.0, 1.0))
