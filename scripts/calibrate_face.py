import sys
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.face import detector
from backend.biometrics.face.lbph import extract_lbph
from backend.biometrics.face.matcher import lbph_similarity

EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.bmp")


def load_dataset(root: Path) -> dict[str, list[np.ndarray]]:
    people: dict[str, list[np.ndarray]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        vectors = []
        for pattern in EXTENSIONS:
            for path in sorted(folder.glob(pattern)):
                face = detector.detect_face(detector.load_image(path.read_bytes()))
                if face is None:
                    print(f"  aviso: sin cara en {path.name}")
                    continue
                vectors.append(extract_lbph(face))
        if len(vectors) >= 2:
            people[folder.name] = vectors
    return people


def equal_error_rate(genuine: list[float], impostor: list[float]) -> tuple[float, float]:
    candidates = sorted(set(genuine + impostor))
    best = (float("inf"), float("nan"), float("nan"))
    for threshold in candidates:
        frr = sum(1 for g in genuine if g < threshold) / len(genuine)
        far = sum(1 for i in impostor if i >= threshold) / len(impostor)
        if abs(far - frr) < best[0]:
            best = (abs(far - frr), threshold, (far + frr) / 2)
    return best[1], best[2]


def main(root: Path, current: float) -> None:
    people = load_dataset(root)
    if len(people) < 2:
        print(f"Se necesitan al menos 2 carpetas de persona con 2+ imagenes en {root}")
        print("Estructura esperada:  datos_cara/<usuario>/<foto>.jpg")
        return

    print(f"Personas: {', '.join(f'{k} ({len(v)})' for k, v in people.items())}")

    genuine, impostor = [], []
    names = list(people)
    for i, name in enumerate(names):
        vectors = people[name]
        for a in range(len(vectors)):
            for b in range(a + 1, len(vectors)):
                genuine.append(lbph_similarity(vectors[a], vectors[b]))
        for other in names[i + 1 :]:
            for va in vectors:
                for vb in people[other]:
                    impostor.append(lbph_similarity(va, vb))

    print(f"\ngenuinos   n={len(genuine):<5} min={min(genuine):.4f} media={np.mean(genuine):.4f}")
    print(f"impostores n={len(impostor):<5} max={max(impostor):.4f} media={np.mean(impostor):.4f}")

    threshold, eer = equal_error_rate(genuine, impostor)
    print(f"\numbral EER={threshold:.4f}  EER={eer * 100:.1f}%")
    frr = sum(1 for g in genuine if g < current) / len(genuine)
    far = sum(1 for i in impostor if i >= current) / len(impostor)
    print(f"con FACE_THRESHOLD={current:.2f} -> FRR={frr * 100:.1f}%  FAR={far * 100:.1f}%")
    print("\nPara un portal, prioriza FAR bajo: sube el umbral por encima del EER.")


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "datos_cara")
    main(path, float(sys.argv[2]) if len(sys.argv) > 2 else 0.70)
