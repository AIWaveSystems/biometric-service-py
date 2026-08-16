import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from backend.biometrics.face import detector, embedder, liveness

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += bool(condition)
    fail += not condition


def sequence(frames):
    out = []
    for frame in frames:
        face = embedder.primary_face(frame)
        out.append(None if face is None else (detector.to_gray(frame), face))
    return out


def closed_eyes(img, sigma=9.0):
    """Simula ojos cerrados difuminando la banda ocular segun los LANDMARKS.

    Anclarlo a los landmarks y no a fracciones fijas es deliberado: si la prueba
    usara las mismas constantes que el detector, se validaria a si misma.
    """
    face = embedder.primary_face(img)
    if face is None:
        return img.copy()
    marks = liveness.landmarks(face)
    d = marks["interocular"]
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.float64)
    cy = marks["eye_center"][1]
    r0, r1 = max(0, int(cy - 0.5 * d)), min(h, int(cy + 0.5 * d))
    c0 = max(0, int(min(marks["right_eye"][0], marks["left_eye"][0]) - 0.5 * d))
    c1 = min(w, int(max(marks["right_eye"][0], marks["left_eye"][0]) + 0.5 * d))
    mask[r0:r1, c0:c1] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), max(2.0, 0.1 * d))[:, :, None]
    smooth = cv2.GaussianBlur(img, (0, 0), sigma).astype(np.float64)
    return (img.astype(np.float64) * (1.0 - mask) + smooth * mask).astype(np.uint8)


img = detector.load_image(open("scripts/lena.jpg", "rb").read())
h, w = img.shape[:2]


def tilt(angle):
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)


print("=== Geometria: la banda ocular debe contener los ojos ===")
dentro = 0
total = 0
for path in sorted(Path("datos_cara").glob("*/*.jpg")) or [Path("scripts/lena.jpg")]:
    probe = detector.load_image(path.read_bytes())
    face = embedder.primary_face(probe)
    if face is None:
        continue
    total += 1
    marks = liveness.landmarks(face)
    banda_lo = marks["eye_center"][1] - liveness.EYE_BAND * marks["interocular"]
    banda_hi = marks["eye_center"][1] + liveness.EYE_BAND * marks["interocular"]
    if banda_lo <= marks["right_eye"][1] <= banda_hi and banda_lo <= marks["left_eye"][1] <= banda_hi:
        dentro += 1
check(
    "los ojos caen dentro de la banda analizada",
    total > 0 and dentro == total,
    f"{dentro}/{total}",
)

print("\n=== Ataques de presentacion (todos deben RECHAZARSE) ===")
attacks = {
    "foto fija repetida": [img] * 28,
    "foto inclinada 25 grados": [tilt(25) if i % 7 in (0, 1) else img for i in range(28)],
    "foto inclinada 30 grados": [tilt(30) if i % 7 in (0, 1) else img for i in range(28)],
    "foto oscilando 0-20 grados": [tilt(20 * abs(np.sin(i / 3))) for i in range(28)],
    "foto con perdidas de deteccion": [img if i % 5 else tilt(45) for i in range(28)],
}
for name, frames in attacks.items():
    result = liveness.analyze(sequence(frames))
    check(
        f"{name} -> sin parpadeo",
        not result["blink_detected"],
        f"caras {result['n_faces']}/{result['n_frames']} gap {result['gap_ratio']}",
    )

print("\n=== Parpadeo sintetico (debe ACEPTARSE) ===")
blink_frames = [img] * 5 + [closed_eyes(img)] * 3 + [img] * 5
result = liveness.analyze(sequence(blink_frames))
check(
    "secuencia abierto-cerrado-abierto -> parpadeo",
    result["blink_detected"],
    f"caras {result['n_faces']}/{result['n_frames']}",
)

print("\n=== Senal sintetica (logica de detect_blink) ===")
check("senal constante -> sin parpadeo", not liveness.detect_blink([1.6] * 10))
check("caida real -> parpadeo", liveness.detect_blink([1.6, 1.6, 1.6, 0.7, 0.7, 1.6, 1.6, 1.6]))
check(
    "huecos de deteccion no cuentan como ojos cerrados",
    not liveness.detect_blink([1.6, 1.6, 1.6, None, None, 1.6, 1.6, 1.6]),
)
check(
    "deriva lenta y superficial -> NO es parpadeo",
    not liveness.detect_blink([1.55, 1.50, 1.46, 1.44, 1.43, 1.38, 1.39, 1.38, 1.43, 1.47]),
)
check(
    "parpadeo pegado al inicio de la rafaga -> se detecta",
    liveness.detect_blink([1.6, 0.9, 0.9, 1.6, 1.6, 1.6]),
)

print("\n=== Rafagas reales (si existen en frames_liveness/) ===")
ESPERADO = {
    "20260815_225621": True,
    "20260815_230138": False,
    "20260815_230204": False,
    "20260815_230229": True,
    "20260815_230243": True,
    "20260815_230257": True,
    "sin_parpadeo_ref": False,
}
encontradas = 0
for name, esperado in ESPERADO.items():
    folder = Path("frames_liveness") / name
    paths = sorted(folder.glob("frame_*.jpg"))
    if not paths:
        continue
    encontradas += 1
    seq = []
    for p in paths:
        frame = detector.load_image(p.read_bytes())
        face = embedder.primary_face(frame)
        seq.append(None if face is None else (detector.to_gray(frame), face))
    got = liveness.analyze(seq)["blink_detected"]
    check(f"{name} -> {'parpadeo' if esperado else 'sin parpadeo'}", got == esperado)
if encontradas == 0:
    print("  (omitido: no hay rafagas grabadas, son datos personales fuera de git)")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
