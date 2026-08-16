import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.face import detector, embedder, liveness

EXTENSIONS = ("*.jpg", "*.jpeg", "*.png")


def main(folder: Path) -> None:
    paths = sorted(p for pattern in EXTENSIONS for p in folder.glob(pattern))
    if not paths:
        print(f"No hay imagenes en {folder}")
        print("Graba una rafaga con:  python scripts/record_blink.py frames_liveness")
        return

    sequence = []
    for path in paths:
        img = detector.load_image(path.read_bytes())
        face = embedder.primary_face(img)
        sequence.append(None if face is None else (detector.to_gray(img), face))

    result = liveness.analyze(sequence)
    signals = result["signals"]
    valid = [s for s in signals if s is not None]
    high = np.percentile(valid, 80) if valid else 0.0
    cut = liveness.BLINK_CLOSED_RATIO * high

    print(f"frames={result['n_frames']} caras={result['n_faces']} "
          f"utiles={result['n_usable']} descartados_por_movimiento={result['n_moved']} "
          f"gap={result['gap_ratio']}")
    print(f"percentil80={high:.3f}  corte_cerrado={cut:.3f}  "
          f"(BLINK_CLOSED_RATIO={liveness.BLINK_CLOSED_RATIO})")
    print(f"parpadeo detectado: {result['blink_detected']}\n")

    for path, signal in zip(paths, signals):
        if signal is None:
            print(f"  {path.name:<24}    sin cara o con movimiento")
            continue
        bar = "#" * int(signal / max(high, 1e-6) * 40)
        mark = "CERRADO" if signal < cut else "abierto"
        print(f"  {path.name:<24} {signal:7.3f} {mark:<8} {bar}")

    print("\nSi tu parpadeo real no baja del corte, sube BLINK_CLOSED_RATIO en liveness.py.")
    print("Si frames con ojos abiertos caen por debajo, bajalo.")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "frames_liveness"))
