import sys

sys.path.insert(0, ".")

import numpy as np
from backend.biometrics.face import detector
from backend.biometrics.face.lbph import extract_lbph
from backend.biometrics.face.matcher import lbph_similarity


def feat(path):
    img = detector.load_image(open(path, "rb").read())
    face = detector.detect_face(img)
    assert face is not None, f"No se detecto cara en {path}"
    return extract_lbph(face)


lena = feat("scripts/lena.jpg")
messi = feat("scripts/messi.jpg")

print("Lena vs Lena (identica):", round(lbph_similarity(lena, lena), 4))
print("Lena vs Messi:", round(lbph_similarity(lena, messi), 4))
print("Messi vs Messi (identica):", round(lbph_similarity(messi, messi), 4))
