import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.voice import pipeline, wav

SAMPLE_RATE = 16000
COUNTDOWN = 3
SECONDS_PER_DIGIT = 1.4
TAIL = 1.0
OUTDIR = Path("datos_digitos")

USO = """Graba la matricula de digitos para el desafio por voz.

Uso:
  python scripts/record_digits.py <usuario>              graba 0..9 (matricula completa)
  python scripts/record_digits.py <usuario> 3 7 1 9      graba solo esos digitos (respuesta
                                                          a un desafio)
  python scripts/record_digits.py dispositivos           lista las tarjetas de audio

Opciones:
  --entrada N   indice del dispositivo de ENTRADA (microfono)
  --pausa S     segundos por digito (por defecto 1.4)

Como funciona: la herramienta te muestra un digito cada vez y graba en continuo.
Di el digito EN VOZ ALTA justo cuando aparezca y CALLA hasta el siguiente. El
silencio entre digitos es lo que permite trocear la toma en el servidor: si
hablas encima de la pausa, el troceo devuelve menos locuciones de las esperadas
y la matricula se rechaza sin tocar lo que ya tenias.

Al terminar comprueba el troceo localmente y te dice si la toma sirve antes de
que la subas.
"""


def _sd():
    try:
        import sounddevice as sd
    except ImportError:
        print("Falta el paquete 'sounddevice'. Instalalo con:")
        print("  pip install sounddevice")
        print("(solo es necesario para esta herramienta, no para el servicio)")
        raise SystemExit(1)
    return sd


def listar_dispositivos() -> int:
    sd = _sd()
    print(sd.query_devices())
    return 0


def grabar(digitos: list[str], segundos: float, entrada: int | None) -> np.ndarray:
    sd = _sd()
    total = COUNTDOWN + len(digitos) * segundos + TAIL
    n = int(total * SAMPLE_RATE)

    print(f"\nVas a decir {len(digitos)} digitos: {' '.join(digitos)}")
    print(f"Duracion total {total:.1f} s. Di cada digito cuando aparezca y calla despues.\n")

    grabacion = sd.rec(n, samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=entrada)
    inicio = time.monotonic()

    for i in range(COUNTDOWN, 0, -1):
        print(f"  {i}...", flush=True)
        time.sleep(max(0.0, (COUNTDOWN - i + 1) - (time.monotonic() - inicio)))

    for k, digito in enumerate(digitos):
        objetivo = COUNTDOWN + k * segundos
        time.sleep(max(0.0, objetivo - (time.monotonic() - inicio)))
        print(f"  >>> {digito} <<<", flush=True)

    sd.wait()
    return grabacion.reshape(-1)


def revisar(x: np.ndarray, digitos: list[str]) -> bool:
    pico = float(np.abs(x).max())
    db = 20 * np.log10(max(pico, 1e-9))
    print(f"\n  nivel de pico: {db:.1f} dBFS")
    if db < -45:
        print("  AVISO: la toma esta practicamente muda. Sube el microfono y repite.")
    elif db > -1.0:
        print("  AVISO: la toma satura. Baja el microfono o alejate un poco.")

    feat, mask, _ = pipeline.utterance_features(np.asarray(x, dtype=np.float64))
    rangos = pipeline.segment_ranges(mask)
    print(f"  locuciones detectadas: {len(rangos)} (esperadas {len(digitos)})")
    for i, (a, b) in enumerate(rangos):
        etiqueta = digitos[i] if i < len(digitos) else "?"
        print(f"    {i + 1:2d}. digito {etiqueta}  {a * 0.01:5.2f}-{b * 0.01:5.2f} s  {b - a} frames")

    if len(rangos) != len(digitos):
        print("\n  NO SIRVE: el troceo no cuadra. Repite dejando pausas mas marcadas.")
        return False
    cortos = [digitos[i] for i, (a, b) in enumerate(rangos) if b - a < pipeline.DIGIT_MIN_FRAMES]
    if cortos:
        print(f"\n  NO SIRVE: digitos demasiado breves ({', '.join(cortos)}). Alargalos.")
        return False
    print("\n  SIRVE: el troceo cuadra con los digitos pedidos.")
    return True


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "ayuda"):
        print(USO)
        return 0
    if argv[0] == "dispositivos":
        return listar_dispositivos()

    entrada = None
    segundos = SECONDS_PER_DIGIT
    resto = []
    i = 0
    while i < len(argv):
        if argv[i] == "--entrada" and i + 1 < len(argv):
            entrada = int(argv[i + 1])
            i += 2
        elif argv[i] == "--pausa" and i + 1 < len(argv):
            segundos = float(argv[i + 1])
            i += 2
        else:
            resto.append(argv[i])
            i += 1

    usuario = resto[0]
    digitos = resto[1:] or list(pipeline.DIGITS)
    invalidos = [d for d in digitos if d not in pipeline.DIGITS]
    if invalidos:
        print(f"Digitos invalidos: {' '.join(invalidos)}. Usa 0..9.")
        return 1

    x = grabar(digitos, segundos, entrada)
    sirve = revisar(x, digitos)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    sello = time.strftime("%Y%m%d_%H%M%S")
    nombre = "matricula" if len(digitos) == 10 else "desafio"
    destino = OUTDIR / f"{usuario}_{nombre}_{sello}.wav"
    destino.write_bytes(wav.write_wav(x.astype(np.float32), SAMPLE_RATE))
    print(f"\n  guardado: {destino}")

    if sirve:
        lista = ",".join(digitos)
        print("\nPara subirlo:")
        print(
            f'  curl -X POST http://127.0.0.1:8000/api/voice/digits/enroll \\\n'
            f'    -H "X-API-Key: TU_API_KEY" \\\n'
            f'    -F "username={usuario}" -F "digits={lista}" \\\n'
            f'    -F "audio=@{destino.as_posix()}"'
        )
    return 0 if sirve else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
