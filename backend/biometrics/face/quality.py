import cv2
import numpy as np

MIN_FACE_SIDE = 80
MIN_SHARPNESS = 70.0
MIN_CONTRAST = 22.0
MAX_CLIPPED_RATIO = 0.28


def sharpness(face: np.ndarray) -> float:
    return float(cv2.Laplacian(face, cv2.CV_64F).var())


def contrast(face: np.ndarray) -> float:
    return float(face.std())


def clipped_ratio(face: np.ndarray) -> float:
    dark = face <= 4
    bright = face >= 251
    return float((dark | bright).mean())


def measure(face: np.ndarray, rect: tuple[int, int, int, int] | None = None) -> dict:
    side = min(rect[2], rect[3]) if rect is not None else min(face.shape[:2])
    return {
        "face_side": int(side),
        "sharpness": round(sharpness(face), 2),
        "contrast": round(contrast(face), 2),
        "clipped": round(clipped_ratio(face), 4),
    }


def check(metrics: dict) -> str | None:
    if metrics["face_side"] < MIN_FACE_SIDE:
        return "Rostro demasiado pequeno o lejano. Acercate a la camara."
    if metrics["sharpness"] < MIN_SHARPNESS:
        return "Imagen borrosa o desenfocada. Mantente quieto y repite la captura."
    if metrics["contrast"] < MIN_CONTRAST:
        return "Contraste insuficiente. Mejora la iluminacion del rostro."
    if metrics["clipped"] > MAX_CLIPPED_RATIO:
        return "Iluminacion extrema (zonas quemadas o en sombra). Evita el contraluz."
    return None


def evaluate(face: np.ndarray, rect: tuple[int, int, int, int] | None = None) -> tuple[dict, str | None]:
    metrics = measure(face, rect)
    return metrics, check(metrics)
