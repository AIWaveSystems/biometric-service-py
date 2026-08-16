import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PORTAL_USER = os.environ.get("PORTAL_USER", "admin")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "admin123")

SELLO = int(time.time())

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += bool(condition)
    fail += not condition


token = requests.post(
    f"{BASE}/api/portal/auth", json={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

creadas = []


def crear(nombre, scopes, dias=None):
    body = {"name": f"{nombre}_{SELLO}", "scopes": scopes}
    if dias is not None:
        body["expires_in_days"] = dias
    r = requests.post(f"{BASE}/api/clients", headers=H, json=body).json()
    creadas.append(r["uuid"])
    return r


def con(key):
    return {"X-API-Key": key}


try:
    print("=== Sin credenciales ===")
    check("sin cabecera -> 401", requests.get(f"{BASE}/api/users").status_code == 401)
    check(
        "X-API-Key vacia -> 401",
        requests.get(f"{BASE}/api/users", headers={"X-API-Key": ""}).status_code == 401,
    )

    print("\n=== Claves mal formadas o inexistentes ===")
    for etiqueta, clave in [
        ("basura", "esto_no_es_una_clave"),
        ("sin prefijo lbs", "xyz_a1b2c3d4e5f6_secreto"),
        ("solo dos partes", "lbs_a1b2c3d4e5f6"),
        ("prefijo inexistente", "lbs_ffffffffffff_secreto"),
    ]:
        r = requests.get(f"{BASE}/api/users", headers=con(clave))
        check(f"{etiqueta} -> 401", r.status_code == 401, str(r.status_code))

    print("\n=== Prefijo real con secreto equivocado ===")
    real = crear("k_auth", ["auth"])
    prefijo = real["api_key"].split("_")[1]
    r = requests.post(
        f"{BASE}/api/auth/login",
        headers=con(f"lbs_{prefijo}_secreto_inventado"),
        json={"username": "nadie", "password": "x"},
    )
    check(
        "prefijo valido + secreto falso -> 401",
        r.status_code == 401,
        f"{r.status_code} (el hash HMAC no cuadra)",
    )

    print("\n=== Permisos por scope ===")
    solo_auth = real["api_key"]
    solo_enroll = crear("k_enroll", ["enroll"])["api_key"]
    admin = crear("k_admin", ["admin", "auth", "enroll"])["api_key"]

    r = requests.get(f"{BASE}/api/users", headers=con(solo_auth))
    check("scope auth en ruta admin -> 403", r.status_code == 403, str(r.json().get("detail")))

    r = requests.post(
        f"{BASE}/api/users/register", headers=con(solo_auth), data={"username": f"x{SELLO}"}
    )
    check("scope auth en ruta enroll -> 403", r.status_code == 403, str(r.json().get("detail")))

    r = requests.post(
        f"{BASE}/api/auth/login",
        headers=con(solo_auth),
        json={"username": f"inexistente{SELLO}", "password": "x"},
    )
    check(
        "scope auth en ruta auth -> pasa el filtro (401 lo da el login, no el permiso)",
        r.status_code == 401 and "permiso" not in str(r.json().get("detail", "")),
        str(r.json().get("detail")),
    )

    r = requests.get(f"{BASE}/api/users", headers=con(solo_enroll))
    check("scope enroll en ruta admin -> 403", r.status_code == 403)

    r = requests.get(f"{BASE}/api/users", headers=con(admin))
    check("scope admin en ruta admin -> 200", r.status_code == 200)

    print("\n=== Rutas nuevas (desafio de digitos y edicion) ===")
    casos = [
        ("POST", "/api/voice/digits/enroll", solo_auth, 403, "digits/enroll exige enroll"),
        ("POST", "/api/voice/challenge", solo_enroll, 403, "challenge exige auth"),
        ("DELETE", "/api/voice/digits/alguien", solo_auth, 403, "borrar digitos exige admin"),
        ("POST", f"/api/users/x{SELLO}/faces", solo_auth, 403, "anadir caras exige enroll"),
        ("POST", f"/api/users/x{SELLO}/password", solo_enroll, 403, "cambiar clave exige admin"),
        ("POST", f"/api/users/x{SELLO}/rename", solo_enroll, 403, "renombrar exige admin"),
    ]
    for metodo, ruta, clave, esperado, etiqueta in casos:
        r = requests.request(metodo, f"{BASE}{ruta}", headers=con(clave))
        check(f"{etiqueta} -> {esperado}", r.status_code == esperado, str(r.status_code))

    print("\n=== Caducidad ===")
    caducada = crear("k_caducada", ["admin"], dias=1)
    uuid_caducada = caducada["uuid"]
    r = requests.get(f"{BASE}/api/users", headers=con(caducada["api_key"]))
    check("clave con caducidad futura -> 200", r.status_code == 200)

    print("\n=== Revocacion ===")
    revocable = crear("k_revocable", ["admin"])
    r = requests.get(f"{BASE}/api/users", headers=con(revocable["api_key"]))
    check("antes de revocar -> 200", r.status_code == 200)

    requests.post(f"{BASE}/api/clients/{revocable['uuid']}/revoke", headers=H)
    r = requests.get(f"{BASE}/api/users", headers=con(revocable["api_key"]))
    check(
        "despues de revocar -> 401",
        r.status_code == 401,
        "si sale 200, es la cache de 60 s del proceso (limitacion conocida)",
    )

    print("\n=== Rotacion ===")
    rotable = crear("k_rotable", ["admin"])
    vieja = rotable["api_key"]
    nueva = requests.post(f"{BASE}/api/clients/{rotable['uuid']}/rotate", headers=H).json()["api_key"]
    check("la clave rotada es distinta", nueva != vieja)
    r = requests.get(f"{BASE}/api/users", headers=con(nueva))
    check("la clave nueva funciona -> 200", r.status_code == 200)
    r = requests.get(f"{BASE}/api/users", headers=con(vieja))
    check(
        "la clave vieja deja de funcionar -> 401",
        r.status_code == 401,
        "si sale 200, es la cache de 60 s del proceso (limitacion conocida)",
    )

    print("\n=== Scopes invalidos al crear ===")
    r = requests.post(
        f"{BASE}/api/clients", headers=H, json={"name": f"k_malo_{SELLO}", "scopes": ["root"]}
    )
    check("scope inventado -> 400", r.status_code == 400, str(r.json().get("detail"))[:80])
    r = requests.post(
        f"{BASE}/api/clients", headers=H, json={"name": f"k_vacio_{SELLO}", "scopes": []}
    )
    check("lista de scopes vacia -> 400", r.status_code == 400)

    print("\n=== La clave solo se muestra una vez ===")
    listado = requests.get(f"{BASE}/api/clients", headers=H).json()
    fila = next(c for c in listado if c["uuid"] == uuid_caducada)
    check("el listado NO devuelve el secreto", "api_key" not in fila and "key" not in fila, str(sorted(fila.keys())))

    print("\n=== El token de portal sigue funcionando en paralelo ===")
    check("token de portal en ruta admin -> 200", requests.get(f"{BASE}/api/users", headers=H).status_code == 200)
    check(
        "token de portal manipulado -> 401",
        requests.get(
            f"{BASE}/api/users", headers={"Authorization": "Bearer " + "x" * 40}
        ).status_code
        == 401,
    )
finally:
    for uuid in creadas:
        requests.post(f"{BASE}/api/clients/{uuid}/revoke", headers=H)
    print(f"\n  {len(creadas)} claves de prueba revocadas")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
