import cv2
import numpy as np

from . import embedder

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


def find_face_rect(img: np.ndarray) -> tuple[int, int, int, int] | None:
    face = embedder.primary_face(img)
    if face is None:
        return None
    return embedder.face_rect(face, img.shape)


def raw_face(
    img: np.ndarray,
    rect: tuple[int, int, int, int],
) -> np.ndarray:
    gray = to_gray(img)
    x, y, w, h = rect
    return gray[y : y + h, x : x + w]


def normalize_face(
    img: np.ndarray,
    rect: tuple[int, int, int, int],
    size: tuple[int, int] = DEFAULT_FACE_SIZE,
) -> np.ndarray:
    gray = to_gray(img)
    x, y, w, h = rect
    face = gray[y : y + h, x : x + w]
    face = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(face)
    return cv2.resize(face, size, interpolation=cv2.INTER_AREA)


def detect_face(img: np.ndarray, size: tuple[int, int] = DEFAULT_FACE_SIZE) -> np.ndarray | None:
    rect = find_face_rect(img)
    if rect is None:
        return None
    return normalize_face(img, rect, size)
