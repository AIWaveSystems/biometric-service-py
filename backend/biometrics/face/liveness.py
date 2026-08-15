import cv2
import numpy as np

BLINK_CLOSED_RATIO = 0.55
MIN_OPEN_FRAMES = 2
MIN_CLOSED_FRAMES = 2
MIN_FACES = 6
MAX_GAP_RATIO = 0.4
SIGNAL_SIZE = (200, 200)


def _edge_energy(strip: np.ndarray) -> float:
    if strip.size == 0:
        return 0.0
    gx = cv2.Sobel(strip, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(strip, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.hypot(gx, gy).mean())


def openness(face_gray: np.ndarray) -> float:
    face = cv2.resize(face_gray, SIGNAL_SIZE, interpolation=cv2.INTER_AREA)
    h, w = face.shape
    eyes = face[int(h * 0.38) : int(h * 0.55), int(w * 0.15) : int(w * 0.85)]
    lower = face[int(h * 0.60) : int(h * 0.88), int(w * 0.20) : int(w * 0.80)]
    eye_energy = _edge_energy(eyes)
    lower_energy = _edge_energy(lower)
    if lower_energy < 1e-3:
        return 0.0
    return eye_energy / lower_energy


def detect_blink(signals: list[float | None]) -> bool:
    valid = np.array([s is not None for s in signals], dtype=bool)
    n = len(signals)
    if valid.sum() < MIN_OPEN_FRAMES * 2 + MIN_CLOSED_FRAMES:
        return False

    values = np.array([s if s is not None else np.nan for s in signals], dtype=np.float64)
    high = np.percentile(values[valid], 80)
    if not np.isfinite(high) or high <= 0:
        return False

    closed = np.zeros(n, dtype=bool)
    closed[valid] = values[valid] < BLINK_CLOSED_RATIO * high

    def open_span(start: int, end: int) -> bool:
        if start < 0 or end > n:
            return False
        return bool(valid[start:end].all() and not closed[start:end].any())

    i = 0
    while i < n:
        if valid[i] and closed[i]:
            j = i
            while j < n and valid[j] and closed[j]:
                j += 1
            run = j - i
            if (
                run >= MIN_CLOSED_FRAMES
                and open_span(i - MIN_OPEN_FRAMES, i)
                and open_span(j, j + MIN_OPEN_FRAMES)
            ):
                return True
            i = j
        else:
            i += 1
    return False


def analyze(
    faces: list[np.ndarray | None],
    min_faces: int = MIN_FACES,
    max_gap_ratio: float = MAX_GAP_RATIO,
) -> dict:
    signals: list[float | None] = [openness(f) if f is not None else None for f in faces]
    n_frames = len(faces)
    n_faces = sum(1 for f in faces if f is not None)
    gap_ratio = 1.0 - (n_faces / n_frames) if n_frames else 1.0

    enough_faces = n_faces >= min_faces
    stable = gap_ratio <= max_gap_ratio
    blink = detect_blink(signals) if enough_faces and stable else False

    return {
        "signals": [round(s, 2) if s is not None else None for s in signals],
        "blink_detected": blink,
        "n_frames": n_frames,
        "n_faces": n_faces,
        "gap_ratio": round(gap_ratio, 3),
        "face_detected": enough_faces,
        "stable": stable,
    }
