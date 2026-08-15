import numpy as np


class Eigenfaces:
    """Reconocimiento facial con Eigenfaces (PCA) implementado desde 0.

    Se entrena con una galeria de caras (cada fila una cara vectorizada) y
    proyecta cualquier cara nueva al subespacio propio para compararla.
    """

    def __init__(self, n_components: int = 40):
        self.n_components = n_components
        self.mean: np.ndarray | None = None
        self.components: np.ndarray | None = None
        self.singular_values: np.ndarray | None = None
        self.gallery: list[tuple[int, np.ndarray]] = []

    def fit(self, X: np.ndarray, labels: list[int] | None = None):
        """X: matriz (n_muestras, n_pixeles). Guarda la galeria y calcula el
        subespacio propio vía SVD."""
        X = np.asarray(X, dtype=np.float64)
        self.mean = X.mean(axis=0)
        Xc = X - self.mean
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        self.singular_values = S
        k = min(self.n_components, Vt.shape[0])
        self.components = Vt[:k]
        labels = labels if labels is not None else list(range(len(X)))
        self.gallery = list(zip(labels, self.project(X)))
        return self

    def project(self, X: np.ndarray) -> np.ndarray:
        if self.components is None:
            raise RuntimeError("Modelo sin entrenar")
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X[None, :]
        return (X - self.mean) @ self.components.T

    def find_nearest(self, face_vec: np.ndarray) -> tuple[int | None, float]:
        """Devuelve (label, distancia euclidiana) del vecino mas cercano."""
        if not self.gallery:
            return None, float("inf")
        probe = self.project(face_vec)[0]
        best_label, best_dist = None, float("inf")
        for label, ref in self.gallery:
            dist = np.linalg.norm(probe - ref)
            if dist < best_dist:
                best_dist, best_label = dist, label
        return best_label, float(best_dist)


def vectorize(gray: np.ndarray) -> np.ndarray:
    return (gray.astype(np.float64) / 255.0).ravel()
