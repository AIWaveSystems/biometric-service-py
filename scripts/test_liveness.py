import sys

sys.path.insert(0, ".")

import cv2
import numpy as np

from backend.biometrics.face import detector, liveness

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += condition
    fail += not condition


def crops(frames):
    out = []
    for frame in frames:
        gray = detector.to_gray(frame)
        rect = detector.find_face_rect(gray)
        if rect is None:
            out.append(None)
            continue
        x, y, w, h = rect
        out.append(gray[y : y + h, x : x + w])
    return out


def closed_eyes(img, sigma=9.0):
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.float64)
    mask[int(h * 0.38) : int(h * 0.58), :] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), 10)[:, :, None]
    smooth = cv2.GaussianBlur(img, (0, 0), sigma).astype(np.float64)
    out = img.astype(np.float64) * (1.0 - mask) + smooth * mask
    return out.astype(np.uint8)


img = detector.load_image(open("scripts/lena.jpg", "rb").read())
h, w = img.shape[:2]


def tilt(angle):
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)


print("=== Ataques de presentacion (todos deben RECHAZARSE) ===")
attacks = {
    "foto fija repetida": [img] * 28,
    "foto inclinada 25 grados": [tilt(25) if i % 7 in (0, 1) else img for i in range(28)],
    "foto inclinada 30 grados": [tilt(30) if i % 7 in (0, 1) else img for i in range(28)],
    "foto oscilando 0-20 grados": [tilt(20 * abs(np.sin(i / 3))) for i in range(28)],
    "foto con perdidas de deteccion": [img if i % 5 else tilt(45) for i in range(28)],
}
for name, frames in attacks.items():
    result = liveness.analyze(crops(frames))
    check(
        f"{name} -> sin parpadeo",
        not result["blink_detected"],
        f"caras {result['n_faces']}/{result['n_frames']} gap {result['gap_ratio']}",
    )

print("\n=== Parpadeo sintetico (debe ACEPTARSE) ===")
blink_frames = [img] * 4 + [closed_eyes(img)] * 3 + [img] * 5
result = liveness.analyze(crops(blink_frames))
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

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
