import numpy as np


def pre_emphasis(x: np.ndarray, a: float = 0.97) -> np.ndarray:
    """Enfasis de altas frecuencias: y[n] = x[n] - a * x[n-1]."""
    return np.concatenate([x[:1], x[1:] - a * x[:-1]])


def frame_signal(x: np.ndarray, win_len: float, hop_len: float, sample_rate: int) -> np.ndarray:
    """Divide la senal en ventanas solapadas (matriz de frames)."""
    n = int(sample_rate * win_len)
    h = int(sample_rate * hop_len)
    if len(x) < n:
        x = np.concatenate([x, np.zeros(n - len(x))])
    n_frames = 1 + (len(x) - n) // h
    idx = np.arange(n)[None, :] + np.arange(n_frames)[:, None] * h
    return x[idx]


def hamming_window(n: int) -> np.ndarray:
    return 0.54 - 0.46 * np.cos(2.0 * np.pi * np.arange(n) / (n - 1))


def hz_to_mel(f: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + f / 700.0)


def mel_to_hz(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def mel_filterbank(n_fft: int, sample_rate: int, n_mels: int = 26, fmin: float = 0.0, fmax: float | None = None) -> np.ndarray:
    """Banco de filtros Mel triangular (n_mels x (n_fft/2 + 1))."""
    if fmax is None:
        fmax = sample_rate / 2.0
    mel_points = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    bins = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)
    banks = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        if bins[m] > bins[m - 1]:
            banks[m - 1, bins[m - 1] : bins[m]] = (np.arange(bins[m - 1], bins[m]) - bins[m - 1]) / (bins[m] - bins[m - 1])
        if bins[m + 1] > bins[m]:
            banks[m - 1, bins[m] : bins[m + 1]] = (bins[m + 1] - np.arange(bins[m], bins[m + 1])) / (bins[m + 1] - bins[m])
    return banks


def dct_matrix(n_mels: int, n_coeffs: int) -> np.ndarray:
    """Matriz DCT-II ortonormal para extraer los coeficientes cepstrales."""
    n = np.arange(n_mels)
    M = np.zeros((n_coeffs, n_mels))
    for k in range(n_coeffs):
        M[k] = np.sqrt(2.0 / n_mels) * np.cos(np.pi * (n + 0.5) * k / n_mels)
    return M


def delta(feat: np.ndarray, N: int = 2) -> np.ndarray:
    """Derivada temporal (regresion lineal en una ventana de +-N frames)."""
    d = np.zeros_like(feat)
    denom = 2.0 * sum(nn * nn for nn in range(1, N + 1))
    for t in range(len(feat)):
        acc = 0.0
        for nn in range(1, N + 1):
            left = feat[t - nn] if t - nn >= 0 else feat[0]
            right = feat[t + nn] if t + nn < len(feat) else feat[-1]
            acc += nn * (right - left)
        d[t] = acc / denom
    return d


def mfcc(
    x: np.ndarray,
    sample_rate: int = 16000,
    n_mels: int = 26,
    n_mfcc: int = 13,
    win_len: float = 0.025,
    hop_len: float = 0.010,
    n_fft: int = 512,
    with_deltas: bool = True,
) -> np.ndarray:
    """Coeficientes MFCC (n_frames x n_coeffs). Implementacion propia de todo el pipeline."""
    x = pre_emphasis(x)
    frames = frame_signal(x, win_len, hop_len, sample_rate)
    frames = frames * hamming_window(frames.shape[1])
    power = np.abs(np.fft.rfft(frames, n_fft)) ** 2
    mel = power @ mel_filterbank(n_fft, sample_rate, n_mels).T
    mel = np.log(mel + 1e-10)
    cept = mel @ dct_matrix(n_mels, n_mfcc).T
    if with_deltas:
        cept = np.concatenate([cept, delta(cept), delta(delta(cept))], axis=1)
    return cept
