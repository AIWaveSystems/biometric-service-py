import cv2
import numpy as np

BLINK_CLOSED_RATIO = 0.86
MIN_OPEN_FRAMES = 1
MIN_CLOSED_FRAMES = 2
MIN_BLINK_DROP = 0.15
DROP_WINDOW = 2
MIN_FACES = 6
MAX_GAP_RATIO = 0.4

EYE_BAND = 0.38
MOUTH_BAND = 0.38
BAND_MARGIN = 0.35
MAX_MOTION_RATIO = 0.22


def _edge_energy(strip: np.ndarray) -> float:
    if strip.size == 0:
        return 0.0
    gx = cv2.Sobel(strip, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(strip, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.hypot(gx, gy).mean())


def landmarks(face: np.ndarray) -> dict:
    right_eye = np.array([face[4], face[5]], dtype=np.float64)
    left_eye = np.array([face[6], face[7]], dtype=np.float64)
    mouth_right = np.array([face[10], face[11]], dtype=np.float64)
    mouth_left = np.array([face[12], face[13]], dtype=np.float64)
    return {
        "right_eye": right_eye,
        "left_eye": left_eye,
        "eye_center": (right_eye + left_eye) / 2.0,
        "mouth_center": (mouth_right + mouth_left) / 2.0,
        "interocular": float(np.linalg.norm(left_eye - right_eye)),
    }


def _band(gray: np.ndarray, marks: dict, center_y: float, half: float) -> np.ndarray:
    d = marks["interocular"]
    x0 = min(marks["right_eye"][0], marks["left_eye"][0]) - BAND_MARGIN * d
    x1 = max(marks["right_eye"][0], marks["left_eye"][0]) + BAND_MARGIN * d
    r0 = max(0, int(round(center_y - half * d)))
    r1 = min(gray.shape[0], int(round(center_y + half * d)))
    c0 = max(0, int(round(x0)))
    c1 = min(gray.shape[1], int(round(x1)))
    return gray[r0:r1, c0:c1]


def openness(gray: np.ndarray, face: np.ndarray) -> float | None:
    marks = landmarks(face)
    if marks["interocular"] < 8.0:
        return None
    eyes = _band(gray, marks, marks["eye_center"][1], EYE_BAND)
    mouth = _band(gray, marks, marks["mouth_center"][1], MOUTH_BAND)
    if eyes.size == 0 or mouth.size == 0:
        return None
    reference = _edge_energy(mouth)
    if reference < 1e-3:
        return None
    return _edge_energy(eyes) / reference


def _motion_mask(faces: list[np.ndarray | None]) -> list[bool]:
    moved = [False] * len(faces)
    previous = None
    for i, face in enumerate(faces):
        if face is None:
            previous = None
            continue
        marks = landmarks(face)
        if previous is not None and marks["interocular"] > 1e-6:
            shift = float(np.linalg.norm(marks["eye_center"] - previous["eye_center"]))
            if shift / marks["interocular"] > MAX_MOTION_RATIO:
                moved[i] = True
        previous = marks
    return moved


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

    def drop_depth(start: int, end: int) -> float:
        before = values[max(0, start - DROP_WINDOW) : start]
        after = values[end : end + DROP_WINDOW]
        neighbours = np.concatenate([before, after])
        neighbours = neighbours[np.isfinite(neighbours)]
        if neighbours.size == 0:
            return 0.0
        reference = float(neighbours.max())
        if reference <= 0:
            return 0.0
        return (reference - float(np.nanmin(values[start:end]))) / reference

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
                and drop_depth(i, j) >= MIN_BLINK_DROP
            ):
                return True
            i = j
        else:
            i += 1
    return False


def analyze(
    frames: list[tuple[np.ndarray, np.ndarray] | None],
    min_faces: int = MIN_FACES,
    max_gap_ratio: float = MAX_GAP_RATIO,
) -> dict:
    faces = [None if f is None else f[1] for f in frames]
    moved = _motion_mask(faces)

    signals: list[float | None] = []
    for i, item in enumerate(frames):
        if item is None or moved[i]:
            signals.append(None)
            continue
        gray, face = item
        signals.append(openness(gray, face))

    n_frames = len(frames)
    n_faces = sum(1 for f in frames if f is not None)
    n_usable = sum(1 for s in signals if s is not None)
    n_moved = sum(1 for m in moved if m)
    gap_ratio = 1.0 - (n_faces / n_frames) if n_frames else 1.0

    enough_faces = n_faces >= min_faces
    stable = gap_ratio <= max_gap_ratio
    blink = detect_blink(signals) if enough_faces and stable else False

    return {
        "signals": [round(s, 3) if s is not None else None for s in signals],
        "blink_detected": blink,
        "n_frames": n_frames,
        "n_faces": n_faces,
        "n_usable": n_usable,
        "n_moved": n_moved,
        "gap_ratio": round(gap_ratio, 3),
        "face_detected": enough_faces,
        "stable": stable,
    }
