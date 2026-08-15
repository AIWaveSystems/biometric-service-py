import sys
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.face import detector, quality
from backend.biometrics.face.lbph import extract_lbph
from backend.biometrics.face.matcher import lbph_similarity

EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
THRESHOLD = 0.70


def load(path: Path):
    image = detector.load_image(path.read_bytes())
    gray = detector.to_gray(image)
    rect = detector.find_face_rect(gray)
    if rect is None:
        return None, None, None
    face = detector.normalize_face(gray, rect)
    return extract_lbph(face), quality.measure(face, rect), rect


def scan(folder: Path) -> dict[str, np.ndarray]:
    vectors: dict[str, np.ndarray] = {}
    print(f"\n--- {folder.name} ---")
    paths = sorted(p for pattern in EXTENSIONS for p in folder.glob(pattern))
    if not paths:
        print("  (sin imagenes)")
        return vectors

    for path in paths:
        vector, metrics, rect = load(path)
        if vector is None:
            print(f"  {path.name:<26} SIN DETECCION  (cara girada, muy lejos o mal iluminada)")
            continue
        problem = quality.check(metrics)
        area = rect[2] * rect[3]
        state = "OK" if problem is None else f"RECHAZADA: {problem}"
        print(
            f"  {path.name:<26} lado={metrics['face_side']:<5} nitidez={metrics['sharpness']:<8.0f}"
            f" area={area:<8} {state}"
        )
        if problem is None:
            vectors[f"{folder.name}/{path.name}"] = vector
    return vectors


def main(root: Path) -> None:
    if not root.is_dir():
        print(f"No existe la carpeta {root}")
        print("Estructura esperada:  datos_cara/<persona>/<foto>.jpg")
        return

    folders = sorted(p for p in root.iterdir() if p.is_dir())
    if not folders:
        print(f"No hay subcarpetas de persona en {root}")
        return

    print("=== DETECCION Y CALIDAD ===")
    people = {folder.name: scan(folder) for folder in folders}

    usable = {k: v for vectors in people.values() for k, v in vectors.items()}
    if len(usable) < 2:
        print("\nHacen falta al menos 2 imagenes utilizables para comparar.")
        return

    print("\n=== MATRIZ DE SIMILITUD ===")
    keys = list(usable)
    width = max(len(k) for k in keys) + 2
    print(" " * width + "".join(f"{k.split('/')[0][:10]:>12}" for k in keys))
    for a in keys:
        row = "".join(f"{lbph_similarity(usable[a], usable[b]):12.4f}" for b in keys)
        print(f"{a:<{width}}{row}")

    genuine, impostor = [], []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            score = lbph_similarity(usable[a], usable[b])
            same = a.split("/")[0] == b.split("/")[0]
            (genuine if same else impostor).append((score, a, b))

    print("\n=== VEREDICTO ===")
    if genuine:
        worst = min(genuine)
        print(f"  genuinos  n={len(genuine):<3} peor={worst[0]:.4f}  ({worst[1]} vs {worst[2]})")
        rejects = [g for g in genuine if g[0] < THRESHOLD]
        print(f"    falsos rechazos con umbral {THRESHOLD}: {len(rejects)}/{len(genuine)}")
    else:
        print("  genuinos  NINGUNO: necesitas 2+ fotos utilizables de la MISMA persona")
    if impostor:
        best = max(impostor)
        print(f"  impostores n={len(impostor):<3} peor={best[0]:.4f}  ({best[1]} vs {best[2]})")
        accepts = [i for i in impostor if i[0] >= THRESHOLD]
        print(f"    falsos positivos con umbral {THRESHOLD}: {len(accepts)}/{len(impostor)}")
    if genuine and impostor:
        margin = min(g[0] for g in genuine) - max(i[0] for i in impostor)
        print(f"\n  SEPARACION = {margin:+.4f}")
        if margin <= 0:
            print("  NEGATIVA: no existe ningun umbral que funcione con estas fotos.")
        else:
            print(f"  Umbral seguro sugerido: {(min(g[0] for g in genuine) + max(i[0] for i in impostor)) / 2:.2f}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "datos_cara"))
