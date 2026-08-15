import os
import sys

sys.path.insert(0, ".")

import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PORTAL_USER = os.environ.get("PORTAL_USER", "admin")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "admin123")

auth = requests.post(
    f"{BASE}/api/portal/auth", json={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
)
if auth.status_code != 200:
    print(f"No se pudo autenticar en el portal ({auth.status_code}).")
    print("Define PORTAL_USER y PORTAL_PASSWORD segun tu .env.")
    sys.exit(1)

H = {"Authorization": f"Bearer {auth.json()['access_token']}"}
FACE = f"{BASE}/api/face"


def image(path):
    return {"image": (os.path.basename(path), open(path, "rb"), "image/jpeg")}


print("=== 1. Registrar usuario 'lena' con su foto ===")
r = requests.post(
    f"{FACE}/register",
    headers=H,
    data={"username": "lena", "password": "secreto123"},
    files=image("scripts/lena.jpg"),
)
print(r.status_code, r.json())

print("\n=== 2. Verificar 'lena' con SU foto (debe pasar) ===")
r = requests.post(
    f"{FACE}/verify", headers=H, data={"username": "lena"}, files=image("scripts/lena.jpg")
)
print(r.status_code, r.json())

print("\n=== 3. Verificar 'lena' con foto de OTRA persona (debe fallar) ===")
r = requests.post(
    f"{FACE}/verify", headers=H, data={"username": "lena"}, files=image("scripts/messi.jpg")
)
print(r.status_code, r.json())

print("\n=== 4. Identificar: quien es esta cara? (lena) ===")
r = requests.post(f"{FACE}/identify", headers=H, files=image("scripts/lena.jpg"))
print(r.status_code, r.json())

print("\n=== 5. Identificar: quien es esta cara? (messi, no registrado) ===")
r = requests.post(f"{FACE}/identify", headers=H, files=image("scripts/messi.jpg"))
print(r.status_code, r.json())

print("\n=== 6. Limpieza ===")
print(requests.delete(f"{BASE}/api/users/lena", headers=H).status_code)
