import numpy as np

_LOG2PI = np.log(2.0 * np.pi)


class GMM:
    """Modelo de mezcla de gaussianas con covarianza diagonal, implementado
    desde 0: inicializacion k-means++ y entrenamiento con EM."""

    def __init__(self, n_components: int = 16):
        self.n_components = n_components
        self.weights: np.ndarray | None = None
        self.means: np.ndarray | None = None
        self.covars: np.ndarray | None = None
        self.log_likelihood: float | None = None
        self.dim: int | None = None

    # ---- inicializacion ----

    def _kmeans_plusplus(self, X: np.ndarray, seed: int = 0) -> np.ndarray:
        rng = np.random.default_rng(seed)
        n = X.shape[0]
        centers = np.empty((self.n_components, X.shape[1]))
        centers[0] = X[rng.integers(n)]
        for i in range(1, self.n_components):
            d2 = np.min([((X - c) ** 2).sum(1) for c in centers[:i]], axis=0)
            total = d2.sum()
            if not np.isfinite(total) or total <= 0:
                centers[i] = X[rng.integers(n)]
                continue
            centers[i] = X[rng.choice(n, p=d2 / total)]
        return centers

    def _refine_kmeans(self, X: np.ndarray, centers: np.ndarray, iters: int = 15) -> np.ndarray:
        for _ in range(iters):
            d = np.array([((X - c) ** 2).sum(1) for c in centers]).T
            assign = d.argmin(1)
            for k in range(self.n_components):
                sel = X[assign == k]
                if len(sel):
                    centers[k] = sel.mean(0)
        return centers

    # ---- log-densidad ----

    def _log_gauss(self, X: np.ndarray) -> np.ndarray:
        diff = X[:, None, :] - self.means[None, :, :]
        log_var = np.log(self.covars).sum(axis=1)[None, :]
        quad = (diff**2 / self.covars[None, :, :]).sum(axis=2)
        logN = -0.5 * (self.dim * _LOG2PI + log_var + quad)
        return logN

    # ---- entrenamiento (EM) ----

    def fit(self, X: np.ndarray, max_iter: int = 100, tol: float = 1e-5, seed: int = 0) -> "GMM":
        X = np.asarray(X, dtype=np.float64)
        n, d = X.shape
        if n < self.n_components:
            self.n_components = max(1, n // 2)
        self.dim = d

        self.means = self._refine_kmeans(X, self._kmeans_plusplus(X, seed))
        self.covars = np.tile(X.var(axis=0) + 1e-4, (self.n_components, 1))
        self.weights = np.full(self.n_components, 1.0 / self.n_components)

        prev = -np.inf
        for _ in range(max_iter):
            logN = self._log_gauss(X)
            logr = logN + np.log(self.weights)[None, :]
            logsum = np.logaddexp.reduce(logr, axis=1, keepdims=True)
            resp = np.exp(logr - logsum)
            total = resp.sum(axis=0)
            total[total < 1e-8] = 1e-8

            self.weights = total / n
            self.means = (resp.T @ X) / total[:, None]
            self.covars = np.maximum((resp.T @ (X**2)) / total[:, None] - self.means**2, 1e-4)

            ll = float(logsum.mean())
            self.log_likelihood = ll
            if abs(ll - prev) < tol:
                break
            prev = ll
        return self

    # ---- scoring ----

    def score(self, X: np.ndarray) -> np.ndarray:
        """Log-verosimilitud por frame (log-likelihood media de cada frame)."""
        X = np.asarray(X, dtype=np.float64)
        logN = self._log_gauss(X)
        return np.logaddexp.reduce(logN + np.log(self.weights)[None, :], axis=1)

    def mean_score(self, X: np.ndarray) -> float:
        s = self.score(X)
        return float(s.mean()) if len(s) else -np.inf
