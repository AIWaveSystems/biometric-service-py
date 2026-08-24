import cv2
import numpy as np

MIN_FACE_SIDE = 80
MIN_SHARPNESS = 70.0
MIN_CONTRAST = 22.0
MAX_CLIPPED_RATIO = 0.28
MAX_TEMPLATE_SIMILARITY = 0.90
MIN_BRIGHTNESS = 55.0
MAX_NOISE_SIGMA = 18.0

_NOISE_KERNEL = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)


def sharpness(face: np.ndarray) -> float:
    return float(cv2.Laplacian(face, cv2.CV_64F).var())


def contrast(face: np.ndarray) -> float:
    return float(face.std())


def brightness(face: np.ndarray) -> float:
    return float(face.mean())


def noise_sigma(face: np.ndarray) -> float:
    im = face.astype(np.float32)
    h, w = im.shape
    if h < 3 or w < 3:
        return 0.0
    resp = cv2.filter2D(im, -1, _NOISE_KERNEL, borderType=cv2.BORDER_REFLECT)
    resp = np.clip(resp, -10.0, 10.0)
    return float(np.sqrt(np.pi / 2) * float(np.abs(resp).sum()) / (6 * (w - 2) * (h - 2)))


def clipped_ratio(face: np.ndarray) -> float:
    dark = face <= 4
    bright = face >= 251
    return float((dark | bright).mean())


def measure(
    face: np.ndarray,
    rect: tuple[int, int, int, int] | None = None,
    raw: np.ndarray | None = None,
) -> dict:
    side = min(rect[2], rect[3]) if rect is not None else min(face.shape[:2])
    source = face if raw is None else raw
    return {
        "face_side": int(side),
        "sharpness": round(sharpness(face), 2),
        "contrast": round(contrast(face), 2),
        "clipped": round(clipped_ratio(face), 4),
        "brightness": round(brightness(source), 2),
        "noise": round(noise_sigma(source), 2),
    }


def check(metrics: dict) -> str | None:
    if metrics["face_side"] < MIN_FACE_SIDE:
        return "Rostro demasiado pequeno o lejano. Acercate a la camara."
    if metrics["brightness"] < MIN_BRIGHTNESS:
        return "Iluminacion muy baja sobre el rostro. Mejora la luz y repite la captura."
    if metrics["sharpness"] < MIN_SHARPNESS:
        return "Imagen borrosa o desenfocada. Mantente quieto y repite la captura."
    if metrics["contrast"] < MIN_CONTRAST:
        return "Contraste insuficiente. Mejora la iluminacion del rostro."
    if metrics["clipped"] > MAX_CLIPPED_RATIO:
        return "Iluminacion extrema (zonas quemadas o en sombra). Evita el contraluz."
    if metrics["noise"] > MAX_NOISE_SIGMA:
        return "Imagen con demasiado ruido. Mejora la iluminacion y repite la captura."
    return None


def evaluate(face: np.ndarray, rect: tuple[int, int, int, int] | None = None) -> tuple[dict, str | None]:
    metrics = measure(face, rect)
    return metrics, check(metrics)


def is_redundant(vector: np.ndarray, accepted: list[np.ndarray]) -> bool:
    from .embedder import similarity

    return any(similarity(vector, other) > MAX_TEMPLATE_SIMILARITY for other in accepted)
