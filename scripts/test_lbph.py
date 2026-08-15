import sys

sys.path.insert(0, ".")

import numpy as np
import cv2

from backend.biometrics.face import detector
from backend.biometrics.face.lbph import extract_lbph
from backend.biometrics.face.matcher import lbph_similarity


def feat(img_bgr):
    face = detector.detect_face(img_bgr)
    assert face is not None, "No se detecto cara"
    return extract_lbph(face)


img = detector.load_image(open("scripts/lena.jpg", "rb").read())
messi = detector.load_image(open("scripts/messi.jpg", "rb").read())

v_base = feat(img)
print("Descriptor LBPH multiescala:", v_base.shape)

# rotar la imagen 12 grados y re-verificar (debe seguir aceptando)
h, w = img.shape[:2]
M = cv2.getRotationMatrix2D((w / 2, h / 2), 12, 1.0)
rotated = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
v_rot = feat(rotated)
print("Misma persona, foto rotada 12° :", round(lbph_similarity(v_base, v_rot), 4))

# cambiar iluminacion (brillo) y re-verificar
dim = np.clip(img.astype(np.float32) * 0.6 + 30, 0, 255).astype(np.uint8)
v_dim = feat(dim)
print("Misma persona, iluminacion baja:", round(lbph_similarity(v_base, v_dim), 4))

# otra persona
v_messi = feat(messi)
print("Persona distinta                :", round(lbph_similarity(v_base, v_messi), 4))

print("\nSeparacion final (mayor = mejor):")
print("  mismo/rotado =", round(lbph_similarity(v_base, v_rot) - lbph_similarity(v_base, v_messi), 4))
