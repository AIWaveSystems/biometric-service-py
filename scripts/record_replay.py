import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

SAMPLE_RATE = 48000
DURATION = 5.0
COUNTDOWN = 3
OUTDIR = Path("datos_replay")

USO = """Uso:
  python scripts/record_replay.py                  graba un PAR completo (por defecto)
  python scripts/record_replay.py par              lo mismo, explicito
  python scripts/record_replay.py genuino          graba solo tu voz al microfono
  python scripts/record_replay.py replay <fichero> reproduce ese fichero por los
                                                   altavoces y lo vuelve a grabar
  python scripts/record_replay.py dispositivos     lista las tarjetas de audio
  python scripts/record_replay.py prueba           busca que ALTAVOZ oye tu microfono
  python scripts/record_replay.py externo <n>      graba el par <n> como REPLAY mientras
                                                   TU reproduces el audio desde fuera

Opciones (validas en par/replay/prueba):
  --salida N    indice del dispositivo de SALIDA (altavoces)
  --entrada N   indice del dispositivo de ENTRADA (microfono)

Si tu salida de audio son AURICULARES o DIADEMA, el modo "par" no puede funcionar:
el sonido va a tus oidos y el microfono no lo capta. Usa una de estas dos:

  1) Apoya el auricular contra el microfono y lanza "par" con el volumen alto.
  2) Graba "genuino", reproduce ese fichero desde el MOVIL cerca del microfono
     y captura con "externo <n>".

Si el replay sale casi mudo, ejecuta "prueba" para ver que salida oye tu microfono.

Un PAR son ~18 s: 3 s de cuenta atras, 5 s grabando tu voz, 2 s de pausa,
3 s de cuenta atras y 5 s reproduciendo por altavoz mientras vuelve a grabar.

Hacen falta 3 o 4 pares. Ejecuta el comando otras tantas veces.

Graba a 48 kHz a proposito: el servicio remuestrea a 16 kHz y ahi se pierden los
agudos, que es justo donde vive parte de la huella del altavoz.
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


def write_wav(path: Path, samples: np.ndarray, rate: int = SAMPLE_RATE) -> None:
    from backend.biometrics.voice import wav

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav.write_wav(np.clip(samples, -1.0, 1.0), rate))


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    from backend.biometrics.voice import wav

    x, rate = wav.read_wav(path.read_bytes())
    return np.asarray(x, dtype=np.float64), rate


def cuenta_atras(mensaje: str) -> None:
    print(f"\n{mensaje}")
    for n in range(COUNTDOWN, 0, -1):
        print(f"  {n}...")
        time.sleep(1.0)


def informe(samples: np.ndarray, etiqueta: str) -> None:
    pico = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
    print(f"  {etiqueta}: pico={pico:.3f} rms={rms:.4f}")
    if pico < 0.02:
        print("  AVISO: casi no se grabo senal. Revisa el microfono o sube el volumen.")
    elif pico > 0.99:
        print("  AVISO: la senal satura. Baja el volumen o alejate del microfono.")


def grabar(segundos: float = DURATION, entrada=None) -> np.ndarray:
    sd = _sd()
    cuenta_atras("Habla con normalidad durante la grabacion.")
    print("  GRABANDO")
    audio = sd.rec(int(segundos * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1,
                   dtype="float32", device=entrada)
    sd.wait()
    return audio.reshape(-1).astype(np.float64)


def reproducir_y_grabar(fuente: Path, segundos: float = DURATION,
                        entrada=None, salida=None) -> np.ndarray:
    sd = _sd()
    x, rate = read_wav(fuente)
    if rate != SAMPLE_RATE:
        from backend.biometrics.voice import wav

        x = wav.resample(x, rate, SAMPLE_RATE)
    total = int(segundos * SAMPLE_RATE)
    if len(x) < total:
        x = np.pad(x, (0, total - len(x)))
    x = x[:total]

    cuenta_atras(
        "Se va a reproducir tu grabacion por los ALTAVOCES y a grabarla de nuevo.\n"
        "Sube el volumen a un nivel normal de conversacion y no hables."
    )
    print("  REPRODUCIENDO Y GRABANDO")
    dispositivo = None
    if entrada is not None or salida is not None:
        dispositivo = (
            entrada if entrada is not None else sd.default.device[0],
            salida if salida is not None else sd.default.device[1],
        )
    grabado = sd.playrec(
        x.astype("float32").reshape(-1, 1),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=dispositivo,
    )
    sd.wait()
    return grabado.reshape(-1).astype(np.float64)


def probar_salidas(entrada=None, salida=None) -> int:
    """Reproduce un tono por cada altavoz y mide cuanto lo capta el microfono."""
    sd = _sd()
    dur = 1.2
    t = np.linspace(0, dur, int(dur * SAMPLE_RATE), endpoint=False)
    tono = (0.35 * (np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 1200 * t))).astype("float32")

    dispositivos = sd.query_devices()
    if salida is not None:
        candidatos = [salida]
    else:
        candidatos = [i for i, d in enumerate(dispositivos) if d["max_output_channels"] > 0]

    print("Midiendo el silencio de fondo...")
    fondo = sd.rec(int(0.8 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1,
                   dtype="float32", device=(entrada, None) if entrada is not None else None)
    sd.wait()
    ref = float(np.sqrt(np.mean(fondo.astype(np.float64) ** 2)))
    print(f"  ruido de fondo: {20 * np.log10(ref + 1e-12):.1f} dB\n")

    print(f"{'idx':>4}  {'dispositivo':<44} {'captado':>9}  veredicto")
    print("-" * 78)
    mejores = []
    for idx in candidatos:
        nombre = dispositivos[idx]["name"][:44]
        try:
            grabado = sd.playrec(
                tono.reshape(-1, 1), samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                device=(entrada if entrada is not None else sd.default.device[0], idx),
            )
            sd.wait()
        except Exception as exc:
            print(f"{idx:>4}  {nombre:<44} {'-':>9}  no se pudo abrir ({type(exc).__name__})")
            continue
        rms = float(np.sqrt(np.mean(grabado.astype(np.float64) ** 2)))
        db = 20 * np.log10(rms + 1e-12)
        ganancia = db - 20 * np.log10(ref + 1e-12)
        if ganancia > 12:
            veredicto = "SIRVE"
            mejores.append((ganancia, idx, nombre))
        elif ganancia > 5:
            veredicto = "flojo, sube el volumen"
        else:
            veredicto = "el microfono no lo oye"
        print(f"{idx:>4}  {nombre:<44} {db:>8.1f} dB  {veredicto}")

    print()
    if mejores:
        mejores.sort(reverse=True)
        g, idx, nombre = mejores[0]
        print(f"Mejor salida: {idx} ({nombre}), +{g:.1f} dB sobre el fondo.")
        print(f"Graba los pares con:")
        print(f"  python scripts/record_replay.py par --salida {idx}")
    else:
        print("Ningun altavoz fue captado por el microfono. Comprueba que:")
        print("  - el volumen del sistema no este al minimo ni silenciado")
        print("  - no tengas auriculares conectados (el sonido se iria por ahi)")
        print("  - el microfono elegido sea el que esta cerca de los altavoces")
    return 0


def siguiente_par() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    usados = [int(p.stem.split("_")[0][3:]) for p in OUTDIR.glob("par*_genuino.wav")]
    return max(usados, default=0) + 1


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "ayuda"):
        print(USO)
        return 0

    entrada = salida = None
    resto = []
    i = 0
    while i < len(argv):
        if argv[i] == "--salida" and i + 1 < len(argv):
            salida = int(argv[i + 1]); i += 2
        elif argv[i] == "--entrada" and i + 1 < len(argv):
            entrada = int(argv[i + 1]); i += 2
        else:
            resto.append(argv[i]); i += 1
    argv = resto

    modo = argv[0] if argv else "par"
    if not argv:
        print("Sin argumentos: se graba un PAR completo.")
        print("Ayuda completa con:  python scripts/record_replay.py --help")

    if modo == "dispositivos":
        sd = _sd()
        for i, d in enumerate(sd.query_devices()):
            marcas = []
            if d["max_input_channels"] > 0:
                marcas.append("entrada")
            if d["max_output_channels"] > 0:
                marcas.append("salida")
            if marcas:
                print(f"  {i:3d}  {'/'.join(marcas):<16} {d['name']}")
        print(f"\npor defecto (entrada, salida): {sd.default.device}")
        return 0

    if modo == "prueba":
        return probar_salidas(entrada, salida)

    if modo == "externo":
        if len(argv) < 2:
            print("Falta el numero de par. Ejemplo:  externo 7")
            print(USO)
            return 1
        n = int(argv[1])
        gen = OUTDIR / f"par{n:02d}_genuino.wav"
        destino = OUTDIR / f"par{n:02d}_replay.wav"
        if not gen.exists():
            print(f"No existe {gen}. Graba primero con:  record_replay.py genuino")
            return 1
        print(f"Vas a capturar el REPLAY del par {n:02d}.")
        print(f"  1. Reproduce {gen} desde el movil (o cualquier altavoz externo).")
        print("  2. Ponlo cerca del microfono, a volumen de conversacion normal.")
        print("  3. Dale a reproducir JUSTO cuando empiece la cuenta atras.")
        audio = grabar(entrada=entrada)
        write_wav(destino, audio)
        informe(audio, "replay")
        print(f"  guardado en {destino}")
        return 0

    if modo == "genuino":
        n = siguiente_par()
        destino = OUTDIR / f"par{n:02d}_genuino.wav"
        audio = grabar(entrada=entrada)
        write_wav(destino, audio)
        informe(audio, "genuino")
        print(f"  guardado en {destino}")
        print(f"\nAhora reproducelo por altavoz con:")
        print(f"  python scripts/record_replay.py replay {destino}")
        return 0

    if modo == "replay":
        if len(argv) < 2:
            print("Falta el fichero a reproducir.\n")
            print(USO)
            return 1
        fuente = Path(argv[1])
        if not fuente.exists():
            print(f"No existe {fuente}")
            return 1
        destino = fuente.with_name(fuente.name.replace("_genuino", "_replay"))
        audio = reproducir_y_grabar(fuente, entrada=entrada, salida=salida)
        write_wav(destino, audio)
        informe(audio, "replay")
        print(f"  guardado en {destino}")
        return 0

    if modo == "par":
        n = siguiente_par()
        print(f"\n=== PAR {n:02d} ===")
        print(f"Duracion total ~18 s. Primero tu voz ({DURATION:.0f} s), luego el altavoz.")
        gen = OUTDIR / f"par{n:02d}_genuino.wav"
        rep = OUTDIR / f"par{n:02d}_replay.wav"

        audio = grabar(entrada=entrada)
        write_wav(gen, audio)
        informe(audio, "genuino")

        print("\n  (pausa de 2 s antes de reproducir)")
        time.sleep(2.0)

        audio = reproducir_y_grabar(gen, entrada=entrada, salida=salida)
        write_wav(rep, audio)
        informe(audio, "replay")

        print(f"\n  PAR {n:02d} COMPLETO")
        print(f"    {gen}")
        print(f"    {rep}")
        print("\nRepite el comando para grabar mas pares (hacen falta 3 o 4).")
        return 0

    print(f"Modo desconocido: {modo}\n")
    print(USO)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
