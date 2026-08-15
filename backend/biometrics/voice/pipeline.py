import io
import threading

import numpy as np

from . import mfcc, wav
from .gmm import GMM

SAMPLE_RATE = 16000
N_COMPONENTS = 8
COHORT_COMPONENTS = 4
UBM_COMPONENTS = 32
MAP_RELEVANCE = 16.0
COHORT_MAX_FRAMES = 40000
MIN_VOICED_FRAMES = 50
MIN_DURATION = 1.0
WIN_LEN = 0.025
HOP_LEN = 0.010
VAD_REL_THRESHOLD = 0.10
CALIBRATION_FOLDS = 3
FRAMES_PER_COMPONENT = 25


def load_audio(data: bytes) -> np.ndarray:
    x, sr = wav.read_wav(data)
    return wav.resample(x, sr, SAMPLE_RATE)


def cmvn(feat: np.ndarray) -> np.ndarray:
    mean = feat.mean(axis=0)
    std = feat.std(axis=0)
    std[std < 1e-6] = 1e-6
    return (feat - mean) / std


def frame_energies(x: np.ndarray, n_frames: int) -> np.ndarray:
    win = int(SAMPLE_RATE * WIN_LEN)
    hop = int(SAMPLE_RATE * HOP_LEN)
    energies = np.zeros(n_frames)
    for i in range(n_frames):
        start = i * hop
        segment = x[start : start + win]
        if len(segment):
            energies[i] = np.sqrt((segment ** 2).mean())
    return energies


def voice_activity_mask(x: np.ndarray, n_frames: int, rel_threshold: float = VAD_REL_THRESHOLD) -> np.ndarray:
    energies = frame_energies(x, n_frames)
    if energies.max() <= 0:
        return np.zeros(n_frames, dtype=bool)
    return energies > max(1e-4, rel_threshold * energies.max())


def extract_features(x: np.ndarray) -> tuple[np.ndarray, float]:
    x = np.asarray(x, dtype=np.float64)
    duration = len(x) / SAMPLE_RATE
    if duration < MIN_DURATION:
        raise ValueError("El audio es demasiado corto (minimo 1 segundo)")

    statics = mfcc.mfcc(x, sample_rate=SAMPLE_RATE, with_deltas=False)
    mask = voice_activity_mask(x, len(statics))
    if not mask.any():
        raise ValueError("No se detecto voz en el audio (audio demasiado silencioso)")

    statics = cmvn(statics)
    feat = np.concatenate(
        [statics, mfcc.delta(statics), mfcc.delta(mfcc.delta(statics))], axis=1
    )
    feat = feat[mask]

    if len(feat) < MIN_VOICED_FRAMES:
        raise ValueError("Demasiado pocos frames de voz para el modelo (habla mas tiempo)")
    return feat, duration


def choose_components(n_frames: int, requested: int = N_COMPONENTS) -> int:
    return int(max(1, min(requested, n_frames // FRAMES_PER_COMPONENT)))


def serialize_gmm(model: GMM) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        weights=model.weights,
        means=model.means,
        covars=model.covars,
        n_components=np.array([model.n_components]),
    )
    return buf.getvalue()


def deserialize_gmm(data: bytes) -> GMM:
    with np.load(io.BytesIO(data)) as z:
        model = GMM(int(z["n_components"][0]))
        model.weights = z["weights"]
        model.means = z["means"]
        model.covars = z["covars"]
        model.dim = model.means.shape[1]
    return model


def fit_gmm(feat: np.ndarray, n_components: int = N_COMPONENTS) -> GMM:
    return GMM(choose_components(len(feat), n_components)).fit(feat)


def calibrate(feat: np.ndarray, n_components: int, folds: int = CALIBRATION_FOLDS) -> tuple[float, float]:
    index = np.arange(len(feat))
    held_out: list[np.ndarray] = []
    for k in range(folds):
        test_mask = index % folds == k
        train_mask = ~test_mask
        if train_mask.sum() < n_components * FRAMES_PER_COMPONENT or test_mask.sum() < 10:
            continue
        fold_model = GMM(n_components).fit(feat[train_mask])
        held_out.append(fold_model.score(feat[test_mask]))

    if not held_out:
        scores = GMM(n_components).fit(feat).score(feat)
    else:
        scores = np.concatenate(held_out)
    return float(scores.mean()), float(scores.std() + 1e-6)


def enroll(feat: np.ndarray, n_components: int = N_COMPONENTS) -> tuple[GMM, float, float]:
    k = choose_components(len(feat), n_components)
    model = GMM(k).fit(feat)
    mean, sigma = calibrate(feat, k)
    return model, mean, sigma


def fit_ubm(background: list[np.ndarray], n_components: int = UBM_COMPONENTS) -> GMM | None:
    pool = [f for f in background if len(f) > 0]
    if not pool:
        return None
    X = np.concatenate(pool, axis=0)
    if len(X) > COHORT_MAX_FRAMES:
        idx = np.linspace(0, len(X) - 1, COHORT_MAX_FRAMES).astype(int)
        X = X[idx]
    return GMM(choose_components(len(X), n_components)).fit(X)


def calibrate_map(feat: np.ndarray, ubm: GMM, folds: int = CALIBRATION_FOLDS) -> tuple[float, float]:
    index = np.arange(len(feat))
    held_out: list[np.ndarray] = []
    for k in range(folds):
        test_mask = index % folds == k
        if test_mask.sum() < 10 or (~test_mask).sum() < 20:
            continue
        fold_model = ubm.map_adapt(feat[~test_mask], relevance=MAP_RELEVANCE)
        held_out.append(fold_model.score(feat[test_mask]) - ubm.score(feat[test_mask]))
    if not held_out:
        scores = ubm.map_adapt(feat, relevance=MAP_RELEVANCE).score(feat) - ubm.score(feat)
    else:
        scores = np.concatenate(held_out)
    return float(scores.mean()), float(scores.std() + 1e-6)


def enroll_map(feat: np.ndarray, ubm: GMM) -> tuple[GMM, float, float]:
    model = ubm.map_adapt(feat, relevance=MAP_RELEVANCE)
    mean, sigma = calibrate_map(feat, ubm)
    return model, mean, sigma


class UbmCache:
    def __init__(self):
        self._key: object = None
        self._model: GMM | None = None
        self._lock = threading.Lock()

    def get(self, key: object, background: list[np.ndarray]) -> GMM | None:
        with self._lock:
            if key != self._key:
                self._model = fit_ubm(background)
                self._key = key
            return self._model

    def invalidate(self) -> None:
        with self._lock:
            self._key = None
            self._model = None


ubm_cache = UbmCache()


class VoiceService:
    def cohort_gmm(self, all_features: list[np.ndarray]) -> GMM | None:
        pool = [f for f in all_features if len(f) > 0]
        if not pool:
            return None
        X = np.concatenate(pool, axis=0)
        if len(X) > COHORT_MAX_FRAMES:
            idx = np.linspace(0, len(X) - 1, COHORT_MAX_FRAMES).astype(int)
            X = X[idx]
        k = choose_components(len(X), COHORT_COMPONENTS)
        return GMM(k).fit(X)

    def verify(
        self,
        target: GMM,
        self_score: float,
        self_sigma: float,
        cohort: GMM | None,
        feat: np.ndarray,
    ) -> tuple[float, float, float | None, bool]:
        ll_target = target.mean_score(feat)
        margin = ll_target - self_score
        z = margin / max(self_sigma, 1e-6)
        if cohort is not None:
            return margin, z, ll_target - cohort.mean_score(feat), True
        return margin, z, None, False

    def verify_ubm(self, target: GMM, ubm: GMM, feat: np.ndarray) -> float:
        return target.mean_score(feat) - ubm.mean_score(feat)


voice_service = VoiceService()
