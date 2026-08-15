import sys

sys.path.insert(0, ".")

import cv2
import numpy as np

from backend.biometrics.face import detector
from backend.biometrics.face.lbph import extract_lbph
from backend.biometrics.face.matcher import lbph_similarity

IDENTITIES = {"lena": "scripts/lena.jpg", "messi": "scripts/messi.jpg"}


def degradations(img: np.ndarray) -> dict[str, np.ndarray]:
    h, w = img.shape[:2]
    rng = np.random.default_rng(0)

    def rotate(angle):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)

    def shift(dx, dy):
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)

    def gamma(g):
        table = ((np.arange(256) / 255.0) ** g * 255).astype(np.uint8)
        return cv2.LUT(img, table)

    def side_light(strength):
        ramp = np.linspace(1.0 - strength, 1.0 + strength, w)[None, :, None]
        return np.clip(img.astype(np.float64) * ramp, 0, 255).astype(np.uint8)

    def jpeg(quality):
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img

    def scale(factor):
        small = cv2.resize(img, (int(w * factor), int(h * factor)))
        return cv2.resize(small, (w, h))

    return {
        "original": img,
        "rot -12": rotate(-12),
        "rot +12": rotate(12),
        "rot +20": rotate(20),
        "desplaz 15px": shift(15, 10),
        "desplaz -20px": shift(-20, -12),
        "gamma 0.5": gamma(0.5),
        "gamma 1.8": gamma(1.8),
        "luz lateral": side_light(0.45),
        "luz lateral inv": side_light(-0.45),
        "jpeg q20": jpeg(20),
        "borroso": cv2.GaussianBlur(img, (0, 0), 2.2),
        "ruido": np.clip(img.astype(np.float64) + rng.normal(0, 14, img.shape), 0, 255).astype(np.uint8),
        "escala 0.5": scale(0.5),
        "contraste bajo": np.clip(img.astype(np.float64) * 0.45 + 70, 0, 255).astype(np.uint8),
    }


def build(extractor) -> dict[str, dict[str, np.ndarray]]:
    out = {}
    for name, path in IDENTITIES.items():
        img = detector.load_image(open(path, "rb").read())
        vectors = {}
        for label, variant in degradations(img).items():
            face = extractor(variant)
            if face is None:
                print(f"  aviso: sin cara en {name} / {label}")
                continue
            vectors[label] = face
        out[name] = vectors
    return out


def default_extractor(img):
    face = detector.detect_face(img)
    return extract_lbph(face) if face is not None else None


def report(vectors: dict[str, dict[str, np.ndarray]], similarity=lbph_similarity) -> None:
    names = list(vectors)
    genuine, impostor = [], []
    worst = []

    for name in names:
        variants = vectors[name]
        if "original" not in variants:
            continue
        base = variants["original"]
        for label, vec in variants.items():
            if label == "original":
                continue
            s = similarity(base, vec)
            genuine.append(s)
            worst.append((s, f"{name} / {label}"))

    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            for va in vectors[a].values():
                for vb in vectors[b].values():
                    impostor.append(similarity(va, vb))

    detected = sum(len(v) for v in vectors.values())
    total = len(names) * len(degradations(detector.load_image(open(IDENTITIES["lena"], "rb").read())))
    print(f"  deteccion            {detected}/{total} variantes")
    print(f"  genuinos   n={len(genuine):<4} min={min(genuine):.4f} media={np.mean(genuine):.4f}")
    print(f"  impostores n={len(impostor):<4} max={max(impostor):.4f} media={np.mean(impostor):.4f}")
    print(f"  SEPARACION (min genuino - max impostor) = {min(genuine) - max(impostor):+.4f}")
    print("  peores casos genuinos:")
    for s, label in sorted(worst)[:4]:
        print(f"    {label:<28} {s:.4f}")


if __name__ == "__main__":
    print("=== PIPELINE ACTUAL ===")
    report(build(default_extractor))
