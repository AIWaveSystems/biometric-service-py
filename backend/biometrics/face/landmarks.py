import threading
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_landmarks_osf.onnx"

INPUT_SIZE = 224
HEATMAP_SIDE = 28
HEATMAP_SCALE = 27.0
LOGIT_FACTOR = 16.0
N_POINTS = 66

CROP_MARGIN_X = 0.10
CROP_MARGIN_Y = 0.125

RIGHT_EYE = (36, 37, 38, 39, 40, 41)
LEFT_EYE = (42, 43, 44, 45, 46, 47)

_IMAGENET_MEAN = np.float32([0.485, 0.456, 0.406])
_IMAGENET_STD = np.float32([0.229, 0.224, 0.225])
_SHIFT = -(_IMAGENET_MEAN / _IMAGENET_STD)
_SCALE = 1.0 / (_IMAGENET_STD * 255.0)

_session: ort.InferenceSession | None = None
_input_name: str = ""
_lock = threading.Lock()


class ModelUnavailable(RuntimeError):
    pass


def available() -> bool:
    return MODEL_PATH.exists()


def _get_session() -> tuple[ort.InferenceSession, str]:
    global _session, _input_name
    if _session is not None:
        return _session, _input_name
    with _lock:
        if _session is None:
            if not MODEL_PATH.exists():
                raise ModelUnavailable(
                    f"Falta {MODEL_PATH.name} en backend/biometrics/face/models. "
                    "Ejecuta: python scripts/fetch_models.py"
                )
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.log_severity_level = 3
            _session = ort.InferenceSession(
                str(MODEL_PATH), sess_options=options, providers=["CPUExecutionProvider"]
            )
            _input_name = _session.get_inputs()[0].name
    return _session, _input_name


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 1e-7, 1.0 - 1e-7)
    return np.log(clipped / (1.0 - clipped)) / LOGIT_FACTOR


def detect(image: np.ndarray, face: np.ndarray) -> np.ndarray | None:
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    height, width = image.shape[:2]
    x, y, w, h = (int(round(v)) for v in face[:4])

    x1 = max(0, min(x - int(w * CROP_MARGIN_X), width - 1))
    y1 = max(0, min(y - int(h * CROP_MARGIN_Y), height - 1))
    x2 = max(0, min(x + w + int(w * CROP_MARGIN_X), width))
    y2 = max(0, min(y + h + int(h * CROP_MARGIN_Y), height))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None

    crop = np.float32(image[y1:y2, x1:x2, ::-1])
    crop = cv2.resize(crop, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_LINEAR)
    crop = crop * _SCALE + _SHIFT
    tensor = np.transpose(crop[None], (0, 3, 1, 2)).astype(np.float32)

    session, name = _get_session()
    output = session.run(None, {name: tensor})[0][0]

    scale_x = (x2 - x1) / INPUT_SIZE
    scale_y = (y2 - y1) / INPUT_SIZE
    span = INPUT_SIZE - 1

    heatmaps = output[0:N_POINTS].reshape(N_POINTS, HEATMAP_SIDE * HEATMAP_SIDE)
    best = heatmaps.argmax(1)
    picked = best[:, None]
    off_a = _logit(np.take_along_axis(output[N_POINTS : 2 * N_POINTS].reshape(N_POINTS, -1), picked, 1).ravel())
    off_b = _logit(np.take_along_axis(output[2 * N_POINTS : 3 * N_POINTS].reshape(N_POINTS, -1), picked, 1).ravel())

    rows = np.floor(best / HEATMAP_SIDE)
    cols = np.floor(np.mod(best, HEATMAP_SIDE))
    py = y1 + scale_y * (span * rows / HEATMAP_SCALE + span * off_a)
    px = x1 + scale_x * (span * cols / HEATMAP_SCALE + span * off_b)

    points = np.stack([px, py], 1).astype(np.float32)
    if not np.isfinite(points).all():
        return None
    return points


def eye_aspect_ratio(points: np.ndarray, indices: tuple[int, ...]) -> float:
    p = points[list(indices)]
    width = float(np.linalg.norm(p[0] - p[3]))
    if width < 1e-6:
        return 0.0
    upper = float(np.linalg.norm(p[1] - p[5]))
    lower = float(np.linalg.norm(p[2] - p[4]))
    return (upper + lower) / (2.0 * width)


def openness(image: np.ndarray, face: np.ndarray) -> float | None:
    points = detect(image, face)
    if points is None:
        return None
    right = eye_aspect_ratio(points, RIGHT_EYE)
    left = eye_aspect_ratio(points, LEFT_EYE)
    if right <= 0.0 and left <= 0.0:
        return None
    return (right + left) / 2.0
