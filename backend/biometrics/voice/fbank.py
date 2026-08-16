import numpy as np

SAMPLE_RATE = 16000
N_MELS = 80
FRAME_LENGTH = 0.025
FRAME_SHIFT = 0.010
PREEMPHASIS = 0.97
LOW_FREQ = 20.0
HIGH_FREQ = 7600.0
EPSILON = 1.19209290e-07


def _hz_to_mel(f):
    return 1127.0 * np.log(1.0 + f / 700.0)


def _mel_to_hz(m):
    return 700.0 * (np.exp(m / 1127.0) - 1.0)


def _filterbank(n_fft: int, sample_rate: int, n_mels: int) -> np.ndarray:
    """Banco triangular en el dominio MEL, como el de Kaldi.

    No reutiliza mfcc.mel_filterbank porque aquel cuantiza los bordes a bins
    enteros; Kaldi los deja continuos y el modelo de WeSpeaker se entreno con la
    version continua. Con la cuantizada los embeddings salen desplazados.
    """
    n_bins = n_fft // 2 + 1
    fft_freqs = np.linspace(0.0, sample_rate / 2.0, n_bins)
    mel_low, mel_high = _hz_to_mel(LOW_FREQ), _hz_to_mel(HIGH_FREQ)
    mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
    hz_points = _mel_to_hz(mel_points)

    banks = np.zeros((n_mels, n_bins))
    for m in range(n_mels):
        left, center, right = hz_points[m], hz_points[m + 1], hz_points[m + 2]
        rising = (fft_freqs - left) / (center - left)
        falling = (right - fft_freqs) / (right - center)
        banks[m] = np.clip(np.minimum(rising, falling), 0.0, None)
    return banks


_BANKS_CACHE: dict[tuple[int, int, int], np.ndarray] = {}


def _banks(n_fft: int, sample_rate: int, n_mels: int) -> np.ndarray:
    key = (n_fft, sample_rate, n_mels)
    if key not in _BANKS_CACHE:
        _BANKS_CACHE[key] = _filterbank(n_fft, sample_rate, n_mels)
    return _BANKS_CACHE[key]


def fbank(x: np.ndarray, sample_rate: int = SAMPLE_RATE, n_mels: int = N_MELS) -> np.ndarray:
    """Log-mel filterbank compatible con kaldi.fbank(window_type='hamming').

    Reproduce el orden exacto de Kaldi porque el modelo espera esa entrada:
    escala a rango int16, quita la continua POR FRAME, preenfasis dentro del
    frame, ventana de Hamming, y logaritmo con suelo. Cambiar el orden de esos
    pasos no rompe nada visible pero degrada el embedding en silencio.
    """
    x = np.asarray(x, dtype=np.float64)
    if np.abs(x).max() <= 1.0:
        x = x * 32768.0

    win = int(round(sample_rate * FRAME_LENGTH))
    hop = int(round(sample_rate * FRAME_SHIFT))
    if len(x) < win:
        raise ValueError("El audio es mas corto que una ventana de analisis")

    n_frames = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + np.arange(n_frames)[:, None] * hop
    frames = x[idx]

    frames = frames - frames.mean(axis=1, keepdims=True)

    emphasised = np.empty_like(frames)
    emphasised[:, 0] = frames[:, 0] - PREEMPHASIS * frames[:, 0]
    emphasised[:, 1:] = frames[:, 1:] - PREEMPHASIS * frames[:, :-1]

    n_fft = 1
    while n_fft < win:
        n_fft *= 2
    windowed = emphasised * np.hamming(win)
    power = np.abs(np.fft.rfft(windowed, n_fft)) ** 2

    energies = power @ _banks(n_fft, sample_rate, n_mels).T
    return np.log(np.maximum(energies, EPSILON)).astype(np.float32)


def cmn(feat: np.ndarray) -> np.ndarray:
    """Resta de la media por coeficiente, que es lo que aplica WeSpeaker."""
    return feat - feat.mean(axis=0, keepdims=True)
