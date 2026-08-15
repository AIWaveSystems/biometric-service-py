import math

import cv2
import numpy as np

_FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

DEFAULT_FACE_SIZE = (200, 200)


def load_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen")
    return img


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def find_face_rect(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    faces = _FACE_CASCADE.detectMultiScale(
        cv2.equalizeHist(gray), scaleFactor=1.1, minNeighbors=5, minSize=(64, 64)
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    ex, ey = int(w * 0.12), int(h * 0.06)
    x = max(0, x - ex)
    y = max(0, y - ey)
    w = min(w + 2 * ex, gray.shape[1] - x)
    h = min(h + 2 * ey, gray.shape[0] - y)
    return int(x), int(y), int(w), int(h)


def _align_face(gray: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = rect
    face = gray[y : y + h, x : x + w]
    eyes = _EYE_CASCADE.detectMultiScale(
        face,
        scaleFactor=1.1,
        minNeighbors=7,
        minSize=(max(8, int(h * 0.07)), max(8, int(h * 0.07))),
        maxSize=(int(w * 0.55), int(h * 0.55)),
    )
    if len(eyes) >= 2:
        eyes = sorted(eyes, key=lambda e: e[0])
        left, right = eyes[0], eyes[-1]
        lc = (left[0] + left[2] / 2, left[1] + left[3] / 2)
        rc = (right[0] + right[2] / 2, right[1] + right[3] / 2)
        angle = math.degrees(math.atan2(rc[1] - lc[1], rc[0] - lc[0]))
        if abs(angle) > 0.3:
            rot = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
            face = cv2.warpAffine(face, rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    return face


def normalize_face(
    gray: np.ndarray,
    rect: tuple[int, int, int, int],
    size: tuple[int, int] = DEFAULT_FACE_SIZE,
) -> np.ndarray:
    face = _align_face(gray, rect)
    face = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(face)
    return cv2.resize(face, size, interpolation=cv2.INTER_AREA)


def detect_face(img: np.ndarray, size: tuple[int, int] = DEFAULT_FACE_SIZE) -> np.ndarray | None:
    gray = to_gray(img)
    rect = find_face_rect(gray)
    if rect is None:
        return None
    return normalize_face(gray, rect, size)
