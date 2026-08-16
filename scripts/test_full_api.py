import os
import sys

sys.path.insert(0, ".")

import cv2
import numpy as np
import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PORTAL_USER = os.environ.get("PORTAL_USER", "admin")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "admin123")

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += condition
    fail += not condition


def portal_auth(user=PORTAL_USER, password=PORTAL_PASSWORD):
    return requests.post(f"{BASE}/api/portal/auth", json={"username": user, "password": password})


# Ruido imperceptible y distinto en cada ejecucion de la suite. Sin el, los bytes
# enviados serian identicos entre ejecuciones y el anti-replay devolveria 409 al
# reejecutar dentro de REPLAY_WINDOW_SECONDS.
_TINT = np.random.default_rng().integers(0, 3, size=(1, 1, 3), dtype=np.int16)


def encode(frame):
    tinted = np.clip(frame.astype(np.int16) + _TINT, 0, 255).astype(np.uint8)
    return cv2.imencode(".jpg", tinted)[1].tobytes()


def blink_sequence(source, n_open=5, n_closed=3):
    """Fabrica abierto-cerrado-abierto difuminando la banda ocular por LANDMARKS.

    Deliberadamente NO usa las constantes de liveness.py: si la prueba creara la
    senal donde el detector la busca, se validaria a si misma.
    """
    from backend.biometrics.face import embedder, liveness

    img = cv2.imread(source)
    face = embedder.primary_face(img)
    if face is None:
        raise SystemExit(f"sin cara detectable en {source}")
    marks = liveness.landmarks(face)
    d = marks["interocular"]
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.float64)
    cy = marks["eye_center"][1]
    r0, r1 = max(0, int(cy - 0.5 * d)), min(h, int(cy + 0.5 * d))
    c0 = max(0, int(min(marks["right_eye"][0], marks["left_eye"][0]) - 0.5 * d))
    c1 = min(w, int(max(marks["right_eye"][0], marks["left_eye"][0]) + 0.5 * d))
    mask[r0:r1, c0:c1] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), max(2.0, 0.1 * d))[:, :, None]
    smooth = cv2.GaussianBlur(img, (0, 0), 9.0).astype(np.float64)
    closed = (img.astype(np.float64) * (1.0 - mask) + smooth * mask).astype(np.uint8)

    frames = [img] * n_open + [closed] * n_closed + [img] * n_open
    return [encode(f) for f in frames]


def frame_files(blobs, tag):
    return [("frames", (f"{tag}{i}.jpg", b, "image/jpeg")) for i, b in enumerate(blobs)]


print("=== 0. Acceso sin autenticar ===")
check("GET /api/users sin token -> 401", requests.get(f"{BASE}/api/users").status_code == 401)
check("GET /docs sin credenciales -> 401", requests.get(f"{BASE}/docs").status_code == 401)
r = requests.get(f"{BASE}/")
check("GET / sirve la app (gate)", r.status_code == 200 and "gate" in r.text)

print("\n=== 1. Autenticacion del portal ===")
r = portal_auth()
check("credenciales correctas", r.status_code == 200 and "access_token" in r.json())
check("credenciales incorrectas -> 401", portal_auth(PORTAL_USER, "incorrecta").status_code == 401)

token = portal_auth().json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

print("\n=== 2. Docs con Basic Auth ===")
r = requests.get(f"{BASE}/docs", auth=(PORTAL_USER, PORTAL_PASSWORD))
check("GET /docs con credenciales -> 200", r.status_code == 200)
check(
    "GET /openapi.json sin credenciales -> 401",
    requests.get(f"{BASE}/openapi.json").status_code == 401,
)

print("\n=== 3. El token de sesion NO abre el portal ===")
requests.post(
    f"{BASE}/api/users/register",
    headers=H,
    data={"username": "carol", "password": "clave123"},
)
r = requests.post(
    f"{BASE}/api/auth/login", headers=H, json={"username": "carol", "password": "clave123"}
)
if r.status_code == 200:
    session = r.json()["access_token"]
    check(
        "token de usuario rechazado en rutas de portal -> 401",
        requests.get(f"{BASE}/api/users", headers={"Authorization": f"Bearer {session}"}).status_code
        == 401,
    )
else:
    check("login de carol", False, r.text[:120])
requests.delete(f"{BASE}/api/users/carol", headers=H)

print("\n=== 4. Limpieza ===")
for u in requests.get(f"{BASE}/api/users", headers=H).json():
    requests.delete(f"{BASE}/api/users/{u['username']}", headers=H)
    print(f"  eliminado {u['username']}")

print("\n=== 5. Registro combinado ===")
r = requests.post(
    f"{BASE}/api/users/register",
    headers=H,
    data={"username": "alice", "password": "clave123"},
    files=[
        ("images", ("lena1.jpg", open("scripts/lena.jpg", "rb"), "image/jpeg")),
        ("images", ("lena2.jpg", open("scripts/lena.jpg", "rb"), "image/jpeg")),
        ("audio", ("a1.wav", open("scripts/A_1.wav", "rb"), "audio/wav")),
    ],
)
check("alice con 2 caras + voz", r.status_code == 200, str(r.json().get("registered")))
check(
    "fotos identicas se descartan por redundancia",
    any("identicas" in s for s in r.json().get("registered", [])),
    str(r.json().get("registered")),
)
r = requests.post(
    f"{BASE}/api/users/register",
    headers=H,
    data={"username": "bob"},
    files=[
        ("images", ("messi_big.jpg", open("scripts/messi_big.jpg", "rb"), "image/jpeg")),
        ("audio", ("b1.wav", open("scripts/B_1.wav", "rb"), "audio/wav")),
    ],
)
check("bob con cara + voz", r.status_code == 200, str(r.json().get("registered")))
r = requests.post(
    f"{BASE}/api/users/register",
    headers=H,
    data={"username": "dave"},
    files=[("audio", ("c1.wav", open("scripts/C_1.wav", "rb"), "audio/wav"))],
)
check("dave con voz (activa el UBM)", r.status_code == 200, str(r.json().get("registered")))

print("\n=== 6. ROSTRO: verificacion simple ===")
r = requests.post(
    f"{BASE}/api/face/verify",
    headers=H,
    data={"username": "alice"},
    files={"image": ("lena.jpg", open("scripts/lena.jpg", "rb"), "image/jpeg")},
).json()
check("alice con su cara -> acepta", r["verified"], f"sim {r['similarity']}")

print("\n=== 7. ROSTRO: login con liveness ===")
r = requests.post(
    f"{BASE}/api/face/login",
    headers=H,
    data={"username": "alice"},
    files=frame_files(blink_sequence("scripts/lena.jpg"), "b"),
).json()
check("alice con parpadeo -> verifica", r["verified"], f"sim {r['similarity']}")
check("el login facial emite token de sesion", bool(r.get("access_token")))

still = [encode(cv2.imread("scripts/lena.jpg"))] * 13
r = requests.post(
    f"{BASE}/api/face/login",
    headers=H,
    data={"username": "alice"},
    files=frame_files(still, "s"),
).json()
check("foto fija sin parpadeo -> rechaza", not r["verified"], str(r.get("reason")))

r = requests.post(
    f"{BASE}/api/face/login",
    headers=H,
    data={"username": "alice"},
    files=frame_files(blink_sequence("scripts/messi_big.jpg"), "m"),
).json()
check("impostor con parpadeo -> rechaza", not r["verified"], f"sim {r['similarity']}")

print("\n=== 8. Anti-replay ===")
replay = blink_sequence("scripts/lena.jpg")
requests.post(
    f"{BASE}/api/face/login",
    headers=H,
    data={"username": "alice"},
    files=frame_files(replay, "r"),
)
r = requests.post(
    f"{BASE}/api/face/login",
    headers=H,
    data={"username": "alice"},
    files=frame_files(replay, "r"),
)
check("reenviar la misma captura -> 409", r.status_code == 409)

print("\n=== 9. VOZ ===")
r = requests.post(
    f"{BASE}/api/voice/verify",
    headers=H,
    data={"username": "alice"},
    files={"audio": ("a2.wav", open("scripts/A_2.wav", "rb"), "audio/wav")},
).json()
check("alice con otra toma suya -> acepta", r["verified"], f"score {r.get('score')} via {r.get('scoring')}")
check("usa UBM-MAP con >=2 locutores de fondo", r.get("scoring") == "ubm-map", f"fondo={r.get('n_background_speakers')}")
r = requests.post(
    f"{BASE}/api/voice/verify",
    headers=H,
    data={"username": "alice"},
    files={"audio": ("b2.wav", open("scripts/B_2.wav", "rb"), "audio/wav")},
).json()
check("alice con voz de bob -> rechaza", not r["verified"], f"score {r.get('score')} via {r.get('scoring')}")

print("\n=== 10. CONTRASENA (body JSON) ===")
r = requests.post(
    f"{BASE}/api/auth/login", headers=H, json={"username": "alice", "password": "clave123"}
)
check("password correcta -> JWT", r.status_code == 200)
r = requests.post(
    f"{BASE}/api/auth/login", headers=H, json={"username": "alice", "password": "mal"}
)
check("password incorrecta -> 401", r.status_code == 401)

print("\n=== 11. Identificacion 1:N ===")
r = requests.post(
    f"{BASE}/api/face/identify",
    headers=H,
    files={"image": ("lena.jpg", open("scripts/lena.jpg", "rb"), "image/jpeg")},
).json()
check("identify reconoce a alice", r.get("username") == "alice", f"sim {r.get('similarity')}")
check("identify devuelve uuid", bool(r.get("uuid")), str(r.get("uuid"))[:8])

print("\n=== 12. Gestion ===")
users = requests.get(f"{BASE}/api/users", headers=H).json()
alice = next(u for u in users if u["username"] == "alice")
check(
    "alice con 1 plantilla (la duplicada se filtro)",
    len(alice["face_templates"]) == 1,
    f"{len(alice['face_templates'])} plantillas",
)
check("borrar bob", requests.delete(f"{BASE}/api/users/bob", headers=H).status_code == 200)

r = requests.post(
    f"{BASE}/api/face/identify",
    headers=H,
    files={"image": ("messi_big.jpg", open("scripts/messi_big.jpg", "rb"), "image/jpeg")},
).json()
check(
    "identify NO inventa usuario tras borrar a bob",
    r.get("username") is None,
    f"sim {r.get('similarity')}",
)

requests.delete(f"{BASE}/api/users/dave", headers=H)

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
