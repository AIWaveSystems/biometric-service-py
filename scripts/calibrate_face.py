import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.face import detector, embedder, quality
from backend.config import settings

EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
ENROLL_TEMPLATES = 3
SWEEP = (0.30, 0.35, 0.363, 0.40, 0.45, 0.50)


def load_dataset(root: Path) -> dict[str, list[np.ndarray]]:
    people: dict[str, list[np.ndarray]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        vectors = []
        for pattern in EXTENSIONS:
            for path in sorted(folder.glob(pattern)):
                image = detector.load_image(path.read_bytes())
                face = embedder.primary_face(image)
                if face is None:
                    print(f"  aviso: sin cara detectada en {path.name}")
                    continue
                rect = embedder.face_rect(face, image.shape)
                problem = quality.check(quality.measure(detector.normalize_face(image, rect), rect))
                if problem is not None:
                    print(f"  aviso: {path.name} descartada -> {problem}")
                    continue
                vectors.append(embedder.embed(image, face))
        if vectors:
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


def pairwise(people: dict[str, list[np.ndarray]]) -> tuple[list[float], list[float]]:
    genuine, impostor = [], []
    names = list(people)
    for i, name in enumerate(names):
        vectors = people[name]
        for a, b in itertools.combinations(range(len(vectors)), 2):
            genuine.append(embedder.similarity(vectors[a], vectors[b]))
        for other in names[i + 1 :]:
            for va in vectors:
                for vb in people[other]:
                    impostor.append(embedder.similarity(va, vb))
    return genuine, impostor


def operating_mode(people: dict[str, list[np.ndarray]]) -> tuple[list[float], list[float]]:
    genuine, impostor = [], []
    for name, vectors in people.items():
        if len(vectors) <= ENROLL_TEMPLATES:
            continue
        others = [v for other, vs in people.items() if other != name for v in vs]
        for combo in itertools.combinations(range(len(vectors)), ENROLL_TEMPLATES):
            enrolled = [vectors[i] for i in combo]
            for j in range(len(vectors)):
                if j not in combo:
                    genuine.append(max(embedder.similarity(t, vectors[j]) for t in enrolled))
            for v in others:
                impostor.append(max(embedder.similarity(t, v) for t in enrolled))
    return genuine, impostor


def report(title: str, genuine: list[float], impostor: list[float], current: float) -> None:
    print(f"\n=== {title} ===")
    if not genuine or not impostor:
        print("  datos insuficientes")
        return
    print(f"  genuinos   n={len(genuine):<6} peor={min(genuine):.4f} media={np.mean(genuine):.4f}")
    print(f"  impostores n={len(impostor):<6} mejor={max(impostor):.4f} media={np.mean(impostor):.4f}")
    print(f"  separacion {min(genuine) - max(impostor):+.4f}")

    threshold, eer = equal_error_rate(genuine, impostor)
    print(f"  umbral EER={threshold:.4f}  EER={eer * 100:.2f}%")
    print("\n  umbral     FRR      FAR")
    for t in sorted(set(SWEEP) | {round(current, 3)}):
        frr = 100 * sum(1 for g in genuine if g < t) / len(genuine)
        far = 100 * sum(1 for i in impostor if i >= t) / len(impostor)
        mark = "  <- actual" if abs(t - current) < 1e-9 else ""
        print(f"  {t:<10.3f} {frr:6.2f}%  {far:6.2f}%{mark}")


def main(root: Path, current: float) -> None:
    if not root.is_dir():
        print(f"No existe la carpeta {root}")
        print("Estructura esperada:  datos_cara/<usuario>/<foto>.jpg")
        return

    people = load_dataset(root)
    if len(people) < 2:
        print(f"Se necesitan al menos 2 carpetas de persona en {root}")
        return
    if not any(len(v) >= 2 for v in people.values()):
        print("Al menos una persona necesita 2+ fotos utilizables para medir genuinos.")
        return

    print(f"\nPersonas: {', '.join(f'{k} ({len(v)})' for k, v in people.items())}")

    g, i = pairwise(people)
    report("TODOS LOS PARES", g, i, current)

    g, i = operating_mode(people)
    report(f"MODO REAL (matricula de {ENROLL_TEMPLATES}, mejor plantilla)", g, i, current)

    print("\nEl 'modo real' es el que importa: reproduce lo que hace /api/face/verify.")
    print("Para un portal prioriza FAR bajo: sube el umbral por encima del EER.")


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "datos_cara")
    main(path, float(sys.argv[2]) if len(sys.argv) > 2 else settings.face_threshold)
