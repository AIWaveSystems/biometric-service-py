import threading
from pathlib import Path

import numpy as np

from . import fbank

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "speaker_resnet34.onnx"
EMBEDDING_DIM = 256
MIN_FRAMES = 100

_session = None
_lock = threading.Lock()


def available() -> bool:
    return MODEL_PATH.exists()


def _get_session():
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            if not available():
                raise RuntimeError(
                    "Falta el modelo de locutor. Ejecuta: python scripts/fetch_models.py"
                )
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            _session = ort.InferenceSession(
                str(MODEL_PATH), options, providers=["CPUExecutionProvider"]
            )
    return _session


def embed(x: np.ndarray) -> np.ndarray:
    feats = fbank.fbank(x)
    if len(feats) < MIN_FRAMES:
        raise ValueError(
            f"El audio es demasiado corto para el modelo de locutor "
            f"({len(feats)} frames, minimo {MIN_FRAMES}). Habla al menos 1.5 segundos."
        )
    batch = fbank.cmn(feats)[None, :, :].astype(np.float32)
    vector = np.asarray(_get_session().run(None, {"feats": batch})[0][0], dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm < 1e-6:
        raise ValueError("El modelo devolvio un embedding nulo")
    return (vector / norm).astype(np.float32)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def best_similarity(probe: np.ndarray, references: list[np.ndarray]) -> float:
    return max((similarity(probe, r) for r in references), default=-1.0)
