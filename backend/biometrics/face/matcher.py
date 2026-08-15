import numpy as np


def chi_square(a: np.ndarray, b: np.ndarray) -> float:
    """Distancia chi-cuadrado entre dos histogramas (clasica para LBPH)."""
    denom = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.divide((a - b) ** 2, denom, out=np.zeros_like(a, dtype=np.float64), where=denom > 0)
    return float(d.sum())


def euclidean(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def distance_to_similarity(dist: float) -> float:
    """Convierte una distancia en una similitud en [0, 1]."""
    return 1.0 / (1.0 + dist)


def lbph_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similitud entre descriptores LBPH en [0, 1] (1 = identico).

    Se usa similitud coseno sobre los vectores normalizados L2: es mucho mas
    robusta a rotaciones, escala e iluminacion que la distancia chi-cuadrado.
    """
    return cosine(a, b)
