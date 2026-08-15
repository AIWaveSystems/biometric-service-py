import io
import struct

import numpy as np


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Lee un WAV PCM (int16 o float32) y devuelve (mono float64 en [-1,1], sample_rate)."""
    if isinstance(data, (bytes, bytearray)):
        data = io.BytesIO(data)
    if data.read(4) != b"RIFF":
        raise ValueError("No es un archivo WAV (falta RIFF)")
    data.read(4)
    if data.read(4) != b"WAVE":
        raise ValueError("No es un archivo WAV (falta WAVE)")

    audio_format = num_channels = sample_rate = bits = None
    pcm = None
    while True:
        chunk = data.read(4)
        if len(chunk) < 4:
            break
        size = struct.unpack("<I", data.read(4))[0]
        body = data.read(size)
        if chunk == b"fmt ":
            audio_format, num_channels, sample_rate, _, _, bits = struct.unpack("<HHIIHH", body[:16])
        elif chunk == b"data":
            pcm = body

    if pcm is None or num_channels is None or sample_rate is None or bits is None:
        raise ValueError("Formato WAV incompleto")
    if bits == 16 and audio_format == 1:
        raw = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768.0
    elif bits == 32 and audio_format == 3:
        raw = np.frombuffer(pcm, dtype=np.float32).astype(np.float64)
    else:
        raise ValueError(f"Formato no soportado: format={audio_format} bits={bits}")
    if num_channels > 1:
        raw = raw.reshape(-1, num_channels).mean(axis=1)
    return raw, sample_rate


def _lowpass(x: np.ndarray, cutoff_ratio: float, taps: int = 101) -> np.ndarray:
    if cutoff_ratio >= 0.5 or len(x) < taps:
        return x
    n = np.arange(taps) - (taps - 1) / 2.0
    kernel = 2.0 * cutoff_ratio * np.sinc(2.0 * cutoff_ratio * n)
    kernel *= np.blackman(taps)
    kernel /= kernel.sum()
    return np.convolve(x, kernel, mode="same")


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    if dst < src:
        x = _lowpass(x, 0.5 * dst / src)
    n = max(1, int(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def write_wav(x: np.ndarray, sample_rate: int = 16000) -> bytes:
    xi = np.clip(np.asarray(x, dtype=np.float64), -1.0, 1.0)
    pcm = (xi * 32767).astype(np.int16)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm) * 2)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm) * 2)
    )
    return header + pcm.tobytes()
