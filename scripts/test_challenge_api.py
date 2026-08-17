import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import requests

from backend.biometrics.voice import pipeline, wav

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
PORTAL_USER = os.environ.get("PORTAL_USER", "admin")
PORTAL_PASSWORD = os.environ.get("PORTAL_PASSWORD", "admin123")

# Usuario propio de esta suite, con sufijo de reloj para no chocar con nadie.
# Solo se borra este; los usuarios reales de la base no se tocan.
USUARIO = f"_prueba_digitos_{int(time.time())}"

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += bool(condition)
    fail += not condition


SR = pipeline.SAMPLE_RATE
_rng = np.random.default_rng(7)

# Cada digito es un timbre distinto: no imita una voz, solo comprueba que el
# troceo, el emparejamiento y los rechazos de la API funcionan de extremo a
# extremo. La precision con voz real se mide con scripts/test_digits.py.
# Cada digito es RUIDO CONFORMADO con una envolvente espectral propia, no tonos.
# Con tonos puros la prueba fallaba de forma intermitente: el MFCC mide la
# envolvente del espectro, y un tono cae en un solo filtro mel, asi que digitos
# vecinos salian casi identicos. Medido, esta version acierta 12/12 entre tomas
# distintas y los tonos se quedaban en 6/10.
_BANDAS = {d: (300 + 320 * i, 180.0) for i, d in enumerate(pipeline.DIGITS)}


def di(digito, dur=0.42, seed=0):
    centro, ancho = _BANDAS[digito]
    r = np.random.default_rng(seed * 100 + int(digito))
    n = int(SR * dur)
    f = np.fft.rfftfreq(n, 1 / SR)
    envolvente = np.exp(-0.5 * ((f - centro) / ancho) ** 2) + 0.25 * np.exp(
        -0.5 * ((f - centro * 2.4) / (ancho * 1.5)) ** 2
    )
    x = np.fft.irfft(np.fft.rfft(r.normal(0, 1, n)) * envolvente, n)
    return x / np.abs(x).max() * 0.6 * np.hanning(n)


def silencio(dur):
    return _rng.normal(0, 0.0008, int(SR * dur))


def toma(digitos, seed=0):
    partes = [silencio(0.4)]
    for d in digitos:
        partes += [di(d, seed=seed), silencio(0.35)]
    return wav.write_wav(np.concatenate(partes).astype(np.float32), SR)


def voz_libre(seconds=4.0, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    sig = sum(np.sin(2 * np.pi * 150 * k * t + rng.uniform(0, 6)) / k for k in range(1, 24))
    sig *= 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
    return wav.write_wav((sig / np.abs(sig).max() * 0.6).astype(np.float32), SR)


token = requests.post(
    f"{BASE}/api/portal/auth", json={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}


def limpiar():
    requests.delete(f"{BASE}/api/users/{USUARIO}", headers=H)


try:
    print(f"=== Preparacion (usuario temporal {USUARIO}) ===")
    r = requests.post(
        f"{BASE}/api/users/register",
        headers=H,
        data={"username": USUARIO, "password": "clave123"},
    )
    check("usuario temporal creado con voz", r.status_code == 200, str(r.json())[:120])

    print("\n=== Matricula de digitos ===")
    r = requests.post(
        f"{BASE}/api/voice/digits/enroll",
        headers=H,
        data={"username": USUARIO, "digits": ",".join(pipeline.DIGITS)},
        files=[("audio", ("d.wav", toma(pipeline.DIGITS, seed=1), "audio/wav"))],
    )
    check("matricula de los 10 digitos", r.status_code == 200, str(r.json())[:140])

    r = requests.post(
        f"{BASE}/api/voice/digits/enroll",
        headers=H,
        data={"username": USUARIO, "digits": "0,1,2,3,4"},
        files=[("audio", ("d.wav", toma(["0", "1", "2"]), "audio/wav"))],
    )
    check(
        "si el troceo no cuadra con los digitos -> 400",
        r.status_code == 400,
        str(r.json().get("detail"))[:110],
    )

    r = requests.get(f"{BASE}/api/voice/digits/{USUARIO}", headers=H).json()
    check("la matricida parcial fallida no borro nada", len(r["enrolled"]) == 10, str(r["enrolled"]))
    check("el usuario figura listo para el desafio", r["ready"] is True)

    print("\n=== Desafio ===")
    ch = requests.post(f"{BASE}/api/voice/challenge", headers=H, data={"username": USUARIO}).json()
    digitos = ch["digits"]
    check("el servidor emite digitos", len(digitos) >= 3, " ".join(digitos))
    check("los digitos son de los matriculados", all(d in pipeline.DIGITS for d in digitos))

    otro = requests.post(
        f"{BASE}/api/voice/challenge", headers=H, data={"username": USUARIO}
    ).json()
    check("dos desafios seguidos tienen id distinto", otro["challenge_id"] != ch["challenge_id"])

    r = requests.post(
        f"{BASE}/api/voice/challenge/verify",
        headers=H,
        data={"username": USUARIO, "challenge_id": ch["challenge_id"]},
        files=[("audio", ("r.wav", toma(digitos, seed=2), "audio/wav"))],
    ).json()
    check(
        "responder los digitos pedidos -> contenido OK",
        r.get("content_ok") is True,
        f"pedidos {digitos} reconocidos {r.get('recognised')}",
    )

    print("\n=== Rechazos ===")
    r = requests.post(
        f"{BASE}/api/voice/challenge/verify",
        headers=H,
        data={"username": USUARIO, "challenge_id": ch["challenge_id"]},
        files=[("audio", ("r.wav", toma(digitos, seed=2), "audio/wav"))],
    )
    check("reutilizar el mismo desafio -> 409", r.status_code == 409, str(r.json().get("detail"))[:80])

    ch2 = requests.post(f"{BASE}/api/voice/challenge", headers=H, data={"username": USUARIO}).json()
    equivocados = [d for d in pipeline.DIGITS if d not in ch2["digits"]][: len(ch2["digits"])]
    r = requests.post(
        f"{BASE}/api/voice/challenge/verify",
        headers=H,
        data={"username": USUARIO, "challenge_id": ch2["challenge_id"]},
        files=[("audio", ("r.wav", toma(equivocados, seed=2), "audio/wav"))],
    ).json()
    check(
        "responder OTROS digitos -> rechazo por contenido",
        r.get("content_ok") is False and r.get("verified") is False,
        f"pedidos {ch2['digits']} dichos {equivocados} reconocidos {r.get('recognised')}",
    )

    ch3 = requests.post(f"{BASE}/api/voice/challenge", headers=H, data={"username": USUARIO}).json()
    r = requests.post(
        f"{BASE}/api/voice/challenge/verify",
        headers=H,
        data={"username": USUARIO, "challenge_id": ch3["challenge_id"]},
        files=[("audio", ("r.wav", toma(ch3["digits"][:2], seed=2), "audio/wav"))],
    ).json()
    check(
        "responder MENOS digitos -> rechazo",
        r.get("verified") is False and r.get("n_segments") != len(ch3["digits"]),
        f"{r.get('n_segments')} locuciones de {len(ch3['digits'])}",
    )

    ch4 = requests.post(f"{BASE}/api/voice/challenge", headers=H, data={"username": USUARIO}).json()
    r = requests.post(
        f"{BASE}/api/voice/challenge/verify",
        headers=H,
        data={"username": USUARIO, "challenge_id": "inventado_" + ch4["challenge_id"][:8]},
        files=[("audio", ("r.wav", toma(ch4["digits"], seed=2), "audio/wav"))],
    )
    check("desafio inventado -> 409", r.status_code == 409)

    print("\n=== Los flujos existentes siguen intactos ===")
    users = requests.get(f"{BASE}/api/users", headers=H).json()
    check(
        "los demas usuarios de la base siguen ahi",
        len([u for u in users if u["username"] != USUARIO]) > 0,
        f"{len(users) - 1} usuarios ajenos intactos",
    )
finally:
    limpiar()
    print(f"\n  usuario temporal {USUARIO} eliminado")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
