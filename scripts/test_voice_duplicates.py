import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from backend.biometrics.voice import embedder, pipeline
from backend.config import settings

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PORTAL_USER = os.environ.get("PORTAL_USER", "admin")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "admin123")

SELLO = int(time.time())
A = f"_dup_a_{SELLO}"
B = f"_dup_b_{SELLO}"

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
UMBRAL = settings.voice_duplicate_threshold


def wav(path):
    return [("audio", (path.name, path.read_bytes(), "audio/wav"))]


def limpiar():
    for u in (A, B):
        requests.delete(f"{BASE}/api/users/{u}", headers=H)


# Que audio sirve depende de QUIEN este ya matriculado en esta base: el guardia
# rechaza cualquier voz que ya exista. En vez de fijar ficheros, la suite mira el
# estado real y elige un grupo libre y una voz ajena a el.
def vecino_mas_parecido(v):
    r = requests.post(
        f"{BASE}/api/voice/identify", headers=H, files=[("audio", ("p.wav", v, "audio/wav"))]
    )
    if r.status_code != 200:
        return 1.0
    ranking = r.json().get("ranking") or []
    return ranking[0]["similarity"] if ranking else -1.0


grupos: dict[str, list[Path]] = {}
for carpeta, patron in [("datos_replay", "*_genuino.wav"), ("scripts", "[ABC]_*.wav")]:
    for p in sorted(Path(carpeta).glob(patron)):
        grupos.setdefault(p.stem.split("_")[0] if carpeta == "scripts" else "real", []).append(p)
grupos = {g: ps for g, ps in grupos.items() if len(ps) >= 3}

if not grupos:
    print("No hay grabaciones suficientes. Omitido.")
    sys.exit(0)

E = {g: [embedder.embed(pipeline.load_audio(p.read_bytes())) for p in ps] for g, ps in grupos.items()}

libres = [g for g in grupos if vecino_mas_parecido(grupos[g][0].read_bytes()) < UMBRAL]
if not libres:
    print("Todas las voces disponibles ya estan matriculadas en esta base.")
    print("Eso ya demuestra que el guardia funciona, pero impide probar el alta. Omitido.")
    sys.exit(0)

TITULAR = libres[0]
AJENO = next(
    (g for g in libres if g != TITULAR and max((a @ b) for a in E[g] for b in E[TITULAR]) < UMBRAL),
    None,
)

print(f"Grupo titular: {TITULAR} ({len(grupos[TITULAR])} tomas)")
print(f"Grupo ajeno:   {AJENO or 'ninguno con similitud < ' + str(UMBRAL)}")

try:
    limpiar()
    print("\n=== Alta del titular ===")
    r = requests.post(
        f"{BASE}/api/users/register", headers=H, data={"username": A}, files=wav(grupos[TITULAR][0])
    )
    check("usuario A creado con voz", r.status_code == 200, str(r.json())[:80])

    print("\n=== La MISMA voz en otra cuenta se rechaza ===")
    r = requests.post(
        f"{BASE}/api/users/register", headers=H, data={"username": B}, files=wav(grupos[TITULAR][1])
    )
    check("alta de B con la voz de A -> 409", r.status_code == 409, str(r.json().get("detail"))[:80])
    listado = [u["username"] for u in requests.get(f"{BASE}/api/users", headers=H).json()]
    check("y B NO se ha creado", B not in listado)

    print("\n=== El titular puede regrabar SU propia voz ===")
    r = requests.post(
        f"{BASE}/api/voice/register", headers=H, data={"username": A}, files=wav(grupos[TITULAR][2])
    )
    check(
        "A regraba su voz -> 200 (no se compara consigo mismo)",
        r.status_code == 200,
        str(r.json().get("message"))[:60],
    )

    print("\n=== Verificacion e identificacion ===")
    r = requests.post(
        f"{BASE}/api/voice/verify", headers=H, data={"username": A}, files=wav(grupos[TITULAR][1])
    ).json()
    check("A entra con su voz", r["verified"], f"{r['scoring']} {r['score']}")

    r = requests.post(f"{BASE}/api/voice/identify", headers=H, files=wav(grupos[TITULAR][0])).json()
    check("identify reconoce a A", r.get("username") == A, f"sim {r.get('similarity')}")
    check(
        "no la marca como ambigua (una sola cuenta con esa voz)",
        r.get("ambiguous") is False,
        str(r.get("matches")),
    )

    if AJENO:
        print("\n=== Una voz DISTINTA si se admite ===")
        r = requests.post(
            f"{BASE}/api/users/register", headers=H, data={"username": B}, files=wav(grupos[AJENO][0])
        )
        check("alta de B con otra voz -> 200", r.status_code == 200, str(r.json().get("registered")))
        r = requests.post(
            f"{BASE}/api/voice/verify", headers=H, data={"username": B}, files=wav(grupos[TITULAR][0])
        ).json()
        check("la voz de A NO entra en B", not r["verified"], f"{r['scoring']} {r['score']}")
    else:
        print("\n=== Una voz DISTINTA si se admite ===")
        print(f"  (omitido: no hay dos grupos con similitud < {UMBRAL} entre si)")
finally:
    limpiar()
    print(f"\n  usuarios temporales {A} y {B} eliminados")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
