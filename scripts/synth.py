import numpy as np

from backend.biometrics.voice import wav


def synthesize_speaker(f0: float, duration: float = 4.0, sr: int = 16000, seed: int = 0, formant: float = 0.9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration * sr)) / sr
    x = np.zeros_like(t)
    for harm in range(1, 25):
        amp = 1.0 / (harm ** 1.3)
        phase = rng.uniform(0, 2 * np.pi)
        x += amp * np.sin(2 * np.pi * f0 * harm * t + phase)
    envelope = 0.7 + 0.3 * np.sin(2 * np.pi * 3.0 * t + rng.uniform(0, np.pi))
    x *= envelope
    x += 0.02 * rng.standard_normal(len(t))
    filt = np.convolve(x, np.array([1.0, formant, 0.3 * formant ** 2]), mode="same")
    return filt / np.max(np.abs(filt))


def _impulse_response(freq: float, bandwidth: float, sr: int, taps: int = 2048) -> np.ndarray:
    r = np.exp(-np.pi * bandwidth / sr)
    theta = 2.0 * np.pi * freq / sr
    gain = (1.0 - r) * np.sqrt(1.0 - 2.0 * r * np.cos(2.0 * theta) + r * r)
    n = np.arange(taps)
    return gain * (r ** n) * np.sin((n + 1) * theta) / max(np.sin(theta), 1e-9)


def _resonator(x: np.ndarray, freq: float, bandwidth: float, sr: int) -> np.ndarray:
    h = _impulse_response(freq, bandwidth, sr)
    size = 1 << int(np.ceil(np.log2(len(x) + len(h) - 1)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)
    return y[: len(x)]


VOWELS = [
    (1.18, 0.79, 0.98, 1.00),
    (0.85, 1.16, 1.05, 1.00),
    (0.44, 1.90, 1.10, 1.02),
    (0.79, 0.72, 0.97, 0.99),
    (0.51, 0.58, 0.96, 0.99),
]


class VocalTract:
    def __init__(self, f0: float, formants: list[float], bandwidths: list[float], jitter: float):
        self.f0 = f0
        self.formants = formants
        self.bandwidths = bandwidths
        self.jitter = jitter


def make_speaker(index: int, rng: np.random.Generator) -> VocalTract:
    base = 95.0 + 130.0 * rng.random()
    scale = 0.82 + 0.36 * rng.random()
    formants = [
        float(np.clip(f * scale * (1.0 + 0.05 * rng.standard_normal()), 200.0, 4200.0))
        for f in (620.0, 1200.0, 2550.0, 3400.0)
    ]
    bandwidths = [float(60.0 + 90.0 * rng.random()) for _ in formants]
    return VocalTract(base, formants, bandwidths, float(0.004 + 0.010 * rng.random()))


def synthesize_utterance(
    speaker: VocalTract,
    seed: int,
    duration: float = 4.0,
    sr: int = 16000,
    noise_level: float = 0.0,
    gain: float = 1.0,
    channel: float = 0.0,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(duration * sr)
    t = np.arange(n) / sr

    drift = 1.0 + 0.06 * np.sin(2.0 * np.pi * 0.35 * t + rng.uniform(0, np.pi))
    jitter = 1.0 + speaker.jitter * rng.standard_normal(n).cumsum() / np.sqrt(n)
    f0_track = speaker.f0 * drift * jitter

    phase = 2.0 * np.pi * np.cumsum(f0_track) / sr
    glottal = np.zeros(n)
    for harm in range(1, 32):
        glottal += np.sin(harm * phase + rng.uniform(0, 2 * np.pi)) / (harm ** 1.25)
    glottal += 0.015 * rng.standard_normal(n)

    n_segments = max(6, int(duration * 4.5))
    bounds = np.linspace(0, n, n_segments + 1).astype(int)
    voiced = np.ones(n)
    weights = np.zeros((len(VOWELS), n))
    for i in range(n_segments):
        s, e = bounds[i], bounds[i + 1]
        if rng.random() < 0.20:
            voiced[s:e] = rng.uniform(0.0, 0.06)
        weights[rng.integers(len(VOWELS)), s:e] = 1.0

    window = np.hanning(1201) / np.hanning(1201).sum()
    voiced = np.convolve(voiced, window, mode="same")
    weights = np.stack([np.convolve(w, window, mode="same") for w in weights])
    weights /= np.maximum(weights.sum(axis=0, keepdims=True), 1e-9)

    x = glottal * voiced
    out = np.zeros(n)
    for vowel_index, vowel in enumerate(VOWELS):
        voice = np.zeros(n)
        for freq, bw, ratio in zip(speaker.formants, speaker.bandwidths, vowel):
            voice += _resonator(x, freq * ratio, bw, sr)
        out += weights[vowel_index] * voice

    if channel:
        out = np.convolve(out, np.array([1.0, channel, 0.35 * channel ** 2]), mode="same")
    if noise_level:
        out = out + noise_level * np.std(out) * rng.standard_normal(n)

    peak = np.max(np.abs(out))
    return gain * out / peak if peak > 0 else out


if __name__ == "__main__":
    for name, f0, seed in [("speakerA", 110.0, 1), ("speakerB", 180.0, 2)]:
        for take in (1, 2):
            path = f"scripts/{name}_take{take}.wav"
            with open(path, "wb") as f:
                f.write(wav.write_wav(synthesize_speaker(f0, seed=seed + take), 16000))
            print("generado", path)
