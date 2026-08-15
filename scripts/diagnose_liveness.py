import sys
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.face import detector, liveness

EXTENSIONS = ("*.jpg", "*.jpeg", "*.png")


def main(folder: Path) -> None:
    paths = sorted(p for pattern in EXTENSIONS for p in folder.glob(pattern))
    if not paths:
        print(f"No hay imagenes en {folder}")
        print("Guarda ahi los frames de una captura real (en orden) y vuelve a ejecutar.")
        return

    crops = []
    for path in paths:
        gray = detector.to_gray(detector.load_image(path.read_bytes()))
        rect = detector.find_face_rect(gray)
        if rect is None:
            crops.append(None)
            continue
        x, y, w, h = rect
        crops.append(gray[y : y + h, x : x + w])

    result = liveness.analyze(crops)
    signals = result["signals"]
    valid = [s for s in signals if s is not None]
    high = np.percentile(valid, 80) if valid else 0.0
    cut = liveness.BLINK_CLOSED_RATIO * high

    print(f"frames={result['n_frames']} caras={result['n_faces']} gap={result['gap_ratio']}")
    print(f"percentil80={high:.3f}  corte_cerrado={cut:.3f}  (BLINK_CLOSED_RATIO={liveness.BLINK_CLOSED_RATIO})")
    print(f"parpadeo detectado: {result['blink_detected']}\n")

    for path, signal in zip(paths, signals):
        if signal is None:
            print(f"  {path.name:<24}    sin cara")
            continue
        bar = "#" * int(signal / max(high, 1e-6) * 40)
        mark = "CERRADO" if signal < cut else "abierto"
        print(f"  {path.name:<24} {signal:7.3f} {mark:<8} {bar}")

    print("\nSi tu parpadeo real no baja del corte, reduce BLINK_CLOSED_RATIO en liveness.py.")
    print("Si frames con ojos abiertos caen por debajo, sube el valor.")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "frames_liveness"))
