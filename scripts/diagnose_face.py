import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.face import detector, embedder, quality
from backend.config import settings

EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.bmp")
THRESHOLD = settings.face_threshold


def load(path: Path):
    image = detector.load_image(path.read_bytes())
    face = embedder.primary_face(image)
    if face is None:
        return None, None, None, None
    rect = embedder.face_rect(face, image.shape)
    normalized = detector.normalize_face(image, rect)
    metrics = quality.measure(normalized, rect)
    return embedder.embed(image, face), metrics, rect, embedder.confidence(face)


def scan(folder: Path) -> dict[str, np.ndarray]:
    vectors: dict[str, np.ndarray] = {}
    print(f"\n--- {folder.name} ---")
    paths = sorted(p for pattern in EXTENSIONS for p in folder.glob(pattern))
    if not paths:
        print("  (sin imagenes)")
        return vectors

    for path in paths:
        vector, metrics, rect, conf = load(path)
        if vector is None:
            print(f"  {path.name:<26} SIN DETECCION  (giro extremo, muy lejos o mal iluminada)")
            continue
        problem = quality.check(metrics)
        state = "OK" if problem is None else f"RECHAZADA: {problem}"
        print(
            f"  {path.name:<26} lado={metrics['face_side']:<5} nitidez={metrics['sharpness']:<8.0f}"
            f" conf={conf:.3f} {state}"
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

    print("=== DETECCION Y CALIDAD (YuNet) ===")
    people = {folder.name: scan(folder) for folder in folders}

    usable = {k: v for vectors in people.values() for k, v in vectors.items()}
    if len(usable) < 2:
        print("\nHacen falta al menos 2 imagenes utilizables para comparar.")
        return

    print("\n=== MATRIZ DE SIMILITUD (SFace, coseno) ===")
    keys = list(usable)
    width = max(len(k) for k in keys) + 2
    print(" " * width + "".join(f"{k.split('/')[0][:10]:>12}" for k in keys))
    for a in keys:
        row = "".join(f"{embedder.similarity(usable[a], usable[b]):12.4f}" for b in keys)
        print(f"{a:<{width}}{row}")

    genuine, impostor = [], []
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            score = embedder.similarity(usable[a], usable[b])
            same = a.split("/")[0] == b.split("/")[0]
            (genuine if same else impostor).append((score, a, b))

    print("\n=== VEREDICTO ===")
    if genuine:
        worst = min(genuine)
        print(f"  genuinos   n={len(genuine):<3} peor={worst[0]:.4f}  ({worst[1]} vs {worst[2]})")
        rejects = [g for g in genuine if g[0] < THRESHOLD]
        print(f"    falsos rechazos con umbral {THRESHOLD}: {len(rejects)}/{len(genuine)}")
    else:
        print("  genuinos   NINGUNO: necesitas 2+ fotos utilizables de la MISMA persona")
    if impostor:
        best = max(impostor)
        print(f"  impostores n={len(impostor):<3} mejor={best[0]:.4f}  ({best[1]} vs {best[2]})")
        accepts = [i for i in impostor if i[0] >= THRESHOLD]
        print(f"    falsos positivos con umbral {THRESHOLD}: {len(accepts)}/{len(impostor)}")
    if genuine and impostor:
        low, high = min(g[0] for g in genuine), max(i[0] for i in impostor)
        print(f"\n  SEPARACION = {low - high:+.4f}")
        if low - high <= 0:
            print("  NEGATIVA: no existe ningun umbral que funcione con estas fotos.")
            print("  Matricula fotos tomadas en momentos distintos, no de una sola sesion.")
        else:
            print(f"  Umbral seguro sugerido: {(low + high) / 2:.3f}  (actual {THRESHOLD})")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "datos_cara"))
