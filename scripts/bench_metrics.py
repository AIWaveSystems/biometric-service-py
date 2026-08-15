import sys

sys.path.insert(0, ".")

import numpy as np
import cv2

from backend.biometrics.face import detector
from backend.biometrics.face.lbph import extract_lbph
from backend.biometrics.face.matcher import chi_square, cosine


def feat(img_bgr):
    face = detector.detect_face(img_bgr)
    return extract_lbph(face) if face is not None else None


def intersection(a, b):
    return float(np.minimum(a, b).sum())


img = detector.load_image(open("scripts/lena.jpg", "rb").read())
messi = detector.load_image(open("scripts/messi.jpg", "rb").read())
h, w = img.shape[:2]
M = cv2.getRotationMatrix2D((w / 2, h / 2), 12, 1.0)
rot = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
dim = np.clip(img.astype(np.float32) * 0.6 + 30, 0, 255).astype(np.uint8)
flip = cv2.flip(img, 1)
small = cv2.resize(img, (int(w * 1.15), int(h * 1.15)))

base = feat(img)
samples = {
    "idéntica": base,
    "rotada 12°": feat(rot),
    "iluminación baja": feat(dim),
    "espejo (flip)": feat(flip),
    "más cercana": feat(small),
}
impostor = feat(messi)

print(f"{'Caso':<20} {'chi-square':>12} {'intersección':>14} {'coseno':>10}")
for name, v in samples.items():
    if v is None:
        print(f"{name:<20} {'sin cara':>12}")
        continue
    cs = 1.0 / (1.0 + chi_square(base, v))
    inter = intersection(base, v)
    cos = cosine(base, v)
    print(f"{name:<20} {cs:12.4f} {inter:14.4f} {cos:10.4f}")
cs = 1.0 / (1.0 + chi_square(base, impostor))
print(f"{'IMPOSTOR':<20} {cs:12.4f} {intersection(base, impostor):14.4f} {cosine(base, impostor):10.4f}")
