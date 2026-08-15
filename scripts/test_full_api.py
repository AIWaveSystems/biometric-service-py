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


def blink_sequence(source, n_open=5, n_closed=3):
    img = cv2.imread(source)
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.float64)
    mask[int(h * 0.38) : int(h * 0.58), :] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), 10)[:, :, None]
    smooth = cv2.GaussianBlur(img, (0, 0), 9.0).astype(np.float64)
    closed = (img.astype(np.float64) * (1.0 - mask) + smooth * mask).astype(np.uint8)

    frames = [img] * n_open + [closed] * n_closed + [img] * n_open
    return [cv2.imencode(".jpg", f)[1].tobytes() for f in frames]


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
r = requests.post(
    f"{BASE}/api/users/register",
    headers=H,
    data={"username": "bob"},
    files=[
        ("images", ("messi.jpg", open("scripts/messi.jpg", "rb"), "image/jpeg")),
        ("audio", ("b1.wav", open("scripts/B_1.wav", "rb"), "audio/wav")),
    ],
)
check("bob con cara + voz", r.status_code == 200, str(r.json().get("registered")))

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

still = [cv2.imencode(".jpg", cv2.imread("scripts/lena.jpg"))[1].tobytes()] * 13
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
    files=frame_files(blink_sequence("scripts/messi.jpg"), "m"),
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
check("alice con otra toma suya -> acepta", r["verified"], f"z {r.get('z_score')} ratio {r.get('ratio')}")
r = requests.post(
    f"{BASE}/api/voice/verify",
    headers=H,
    data={"username": "alice"},
    files={"audio": ("b2.wav", open("scripts/B_2.wav", "rb"), "audio/wav")},
).json()
check("alice con voz de bob -> rechaza", not r["verified"], f"z {r.get('z_score')} ratio {r.get('ratio')}")

print("\n=== 10. CONTRASENA (body JSON) ===")
r = requests.post(
    f"{BASE}/api/auth/login", headers=H, json={"username": "alice", "password": "clave123"}
)
check("password correcta -> JWT", r.status_code == 200)
r = requests.post(
    f"{BASE}/api/auth/login", headers=H, json={"username": "alice", "password": "mal"}
)
check("password incorrecta -> 401", r.status_code == 401)

print("\n=== 11. Gestion ===")
users = requests.get(f"{BASE}/api/users", headers=H).json()
alice = next(u for u in users if u["username"] == "alice")
check("alice con 2 plantillas de cara", len(alice["face_templates"]) == 2)
check("borrar bob", requests.delete(f"{BASE}/api/users/bob", headers=H).status_code == 200)

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
