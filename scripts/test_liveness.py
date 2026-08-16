import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from backend.biometrics.face import detector, embedder, landmarks, liveness

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
        out.append(None if face is None else (frame, face))
    return out


img = detector.load_image(open("scripts/lena.jpg", "rb").read())
h, w = img.shape[:2]


def tilt(angle):
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)


print("=== Modelo de landmarks ===")
check("el modelo esta descargado", landmarks.available(), str(landmarks.MODEL_PATH.name))

face = embedder.primary_face(img)
pts = landmarks.detect(img, face) if face is not None else None
check("devuelve 66 puntos", pts is not None and pts.shape == (66, 2), str(None if pts is None else pts.shape))

if pts is not None:
    marks = liveness.landmarks(face)
    d = marks["interocular"]
    ojo_der = pts[list(landmarks.RIGHT_EYE)].mean(axis=0)
    ojo_izq = pts[list(landmarks.LEFT_EYE)].mean(axis=0)
    err = (
        np.linalg.norm(ojo_der - marks["right_eye"]) + np.linalg.norm(ojo_izq - marks["left_eye"])
    ) / 2.0
    check(
        "los puntos oculares coinciden con los ojos que da YuNet",
        err < 0.35 * d,
        f"error {err:.1f}px sobre {d:.1f}px interoculares",
    )
    ear = liveness.openness(img, face)
    check("EAR de ojos abiertos en rango plausible", ear is not None and 0.15 < ear < 0.45, f"{ear:.3f}")

print("\n=== EAR distingue abierto de cerrado (fotos reales) ===")
cerrados = sorted(Path("datos_liveness/cerrados").glob("*.jpg"))
abiertos = sorted(Path("datos_cara/andres").glob("*.jpg"))[:6]
if cerrados and abiertos:
    def ear_de(path):
        probe = detector.load_image(path.read_bytes())
        f = embedder.primary_face(probe)
        return None if f is None else liveness.openness(probe, f)

    vc = [v for v in map(ear_de, cerrados) if v is not None]
    va = [v for v in map(ear_de, abiertos) if v is not None]
    check(
        "EAR cerrado < EAR abierto sin solape",
        vc and va and max(vc) < min(va),
        f"cerrados {min(vc):.3f}-{max(vc):.3f}  abiertos {min(va):.3f}-{max(va):.3f}",
    )
else:
    print("  (omitido: no hay fotos propias, son datos personales fuera de git)")

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

print("\n=== Senal sintetica (logica de detect_blink) ===")
check("senal constante -> sin parpadeo", not liveness.detect_blink([0.27] * 10))
check(
    "caida real -> parpadeo",
    liveness.detect_blink([0.27, 0.27, 0.27, 0.09, 0.09, 0.27, 0.27, 0.27]),
)
check(
    "huecos de deteccion no cuentan como ojos cerrados",
    not liveness.detect_blink([0.27, 0.27, 0.27, None, None, 0.27, 0.27, 0.27]),
)
check(
    "deriva lenta y superficial -> NO es parpadeo",
    not liveness.detect_blink([0.28, 0.27, 0.26, 0.25, 0.25, 0.24, 0.24, 0.25, 0.26, 0.27]),
)
check(
    "parpadeo pegado al inicio de la rafaga -> se detecta",
    liveness.detect_blink([0.27, 0.09, 0.09, 0.27, 0.27, 0.27]),
)

print("\n=== Rafagas reales (si existen en frames_liveness/) ===")
ESPERADO = {
    "20260815_225621": True,
    "20260815_230229": True,
    "20260815_230243": True,
    "20260815_230257": True,
    "20260816_074127": True,
    "20260816_074143": True,
    "20260816_074353": True,
    "20260816_074433": True,
    "20260815_230138": False,
    "20260815_230204": False,
    "sin_parpadeo_ref": False,
}
encontradas = 0
for name, esperado in ESPERADO.items():
    paths = sorted((Path("frames_liveness") / name).glob("frame_*.jpg"))
    if not paths:
        continue
    encontradas += 1
    seq = []
    for p in paths:
        frame = detector.load_image(p.read_bytes())
        f = embedder.primary_face(frame)
        seq.append(None if f is None else (frame, f))
    got = liveness.analyze(seq)["blink_detected"]
    check(f"{name} -> {'parpadeo' if esperado else 'sin parpadeo'}", got == esperado)
if encontradas == 0:
    print("  (omitido: no hay rafagas grabadas, son datos personales fuera de git)")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
