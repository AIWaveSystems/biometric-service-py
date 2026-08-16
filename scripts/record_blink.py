import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

BURST_SECONDS = 2.6
BURST_FPS = 11
COUNTDOWN = 3


def main(outdir: Path, camera: int) -> int:
    cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"No se pudo abrir la camara {camera}.")
        print("Prueba otro indice:  python scripts/record_blink.py frames_liveness 1")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    for _ in range(10):
        cap.read()

    total = int(BURST_SECONDS * BURST_FPS)
    cue = total // 2

    outdir = outdir / time.strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)

    print("Se grabaran %.1f s a ~%d fps (%d frames)." % (BURST_SECONDS, BURST_FPS, total))
    print("MANTEN LOS OJOS ABIERTOS y parpadea SOLO cuando aparezca el aviso.\n")
    for n in range(COUNTDOWN, 0, -1):
        print(f"  {n}...")
        time.sleep(1.0)
    print("  GRABANDO (ojos abiertos)")

    interval = 1.0 / BURST_FPS
    saved = 0
    start = time.monotonic()
    for i in range(total):
        target = start + i * interval
        while time.monotonic() < target:
            pass
        if i == cue:
            print("  >>> PARPADEA AHORA <<<")
        ok, frame = cap.read()
        if not ok:
            continue
        cv2.imwrite(str(outdir / f"frame_{i:03d}.jpg"), frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        saved += 1

    cap.release()
    print(f"\n  LISTO: {saved} frames en {outdir}")
    print("  (cada grabacion va a su propia carpeta, no se sobrescribe nada)\n")
    print("Ahora analiza la rafaga con:")
    print(f"  python scripts/diagnose_liveness.py {outdir}")
    return 0


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "frames_liveness")
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    sys.exit(main(folder, index))
