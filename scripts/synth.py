import numpy as np

from backend.biometrics.voice import wav


def synthesize_speaker(f0: float, duration: float = 4.0, sr: int = 16000, seed: int = 0, formant: float = 0.9) -> np.ndarray:
    """Genera un 'locutor' artificial: armonicos de la F0 + formante + variacion.

    Se usa como sustituto de voz para validar el pipeline sin micrófono.
    """
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


if __name__ == "__main__":
    for name, f0, seed in [("speakerA", 110.0, 1), ("speakerB", 180.0, 2)]:
        for take in (1, 2):
            path = f"scripts/{name}_take{take}.wav"
            with open(path, "wb") as f:
                f.write(wav.write_wav(synthesize_speaker(f0, seed=seed + take), 16000))
            print("generado", path)
