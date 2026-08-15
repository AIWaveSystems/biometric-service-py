import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "backend" / "biometrics" / "face" / "models"
BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"

MODELS = [
    (
        "face_detection_yunet_2023mar.onnx",
        f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        232589,
    ),
    (
        "face_recognition_sface_2021dec.onnx",
        f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        38696353,
    ),
]


def download(name: str, url: str, expected_size: int) -> bool:
    target = MODEL_DIR / name
    if target.exists() and target.stat().st_size == expected_size:
        print(f"  {name}: ya presente ({expected_size} bytes)")
        return True
    print(f"  {name}: descargando...")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
    except Exception as exc:
        print(f"  {name}: ERROR de descarga -> {exc}")
        return False
    if len(data) != expected_size:
        print(f"  {name}: ERROR tamano {len(data)}, esperado {expected_size}")
        return False
    target.write_bytes(data)
    print(f"  {name}: ok ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]})")
    return True


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Destino: {MODEL_DIR}")
    ok = all(download(*m) for m in MODELS)
    if ok:
        print("\nModelos listos.")
        return 0
    print("\nFaltan modelos. El servicio facial no arrancara.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
