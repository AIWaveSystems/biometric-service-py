import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "backend" / "biometrics" / "face" / "models"
VOICE_DIR = ROOT / "backend" / "biometrics" / "voice" / "models"
BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
OSF = "https://raw.githubusercontent.com/emilianavt/OpenSeeFace/master/models"
WESPEAKER = "https://huggingface.co/hbredin/wespeaker-voxceleb-resnet34-LM/resolve/main"

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
    (
        "face_landmarks_osf.onnx",
        f"{OSF}/lm_model3_opt.onnx",
        13500226,
    ),
]

VOICE_MODELS = [
    (
        "speaker_resnet34.onnx",
        f"{WESPEAKER}/speaker-embedding.onnx",
        26530309,
    ),
]


def download(directory: Path, name: str, url: str, expected_size: int) -> bool:
    target = directory / name
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
    VOICE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Rostro -> {MODEL_DIR}")
    ok_face = all(download(MODEL_DIR, *m) for m in MODELS)

    print(f"\nVoz -> {VOICE_DIR}")
    ok_voice = all(download(VOICE_DIR, *m) for m in VOICE_MODELS)

    if ok_face and ok_voice:
        print("\nModelos listos.")
        return 0
    if not ok_face:
        print("\nFaltan modelos faciales. El servicio no arrancara.")
    if not ok_voice:
        print(
            "\nFalta el modelo de voz. El servicio arranca igual, pero la verificacion\n"
            "de locutor cae al camino antiguo (MFCC+GMM), bastante menos preciso."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
