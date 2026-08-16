import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.voice import embedder, fbank, pipeline
from backend.config import settings

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += bool(condition)
    fail += not condition


print("=== Modelo ===")
check("el modelo esta descargado", embedder.available(), embedder.MODEL_PATH.name)
if not embedder.available():
    print("\n  Ejecuta: python scripts/fetch_models.py")
    sys.exit(1)

SR = pipeline.SAMPLE_RATE
rng = np.random.default_rng(0)
tono = np.sin(2 * np.pi * 180 * np.arange(SR * 3) / SR) * 0.5

print("\n=== Fbank ===")
f = fbank.fbank(tono)
check("80 bandas", f.shape[1] == 80, str(f.shape))
check(
    "numero de frames como Kaldi (snip_edges)",
    len(f) == 1 + (len(tono) - 400) // 160,
    f"{len(f)} frames",
)
check("sin NaN ni infinitos", np.isfinite(f).all())
check(
    "la escala de entrada no cambia el resultado",
    np.allclose(fbank.fbank(tono), fbank.fbank(tono * 32768.0), atol=1e-3),
    "float -1..1 y rango int16 dan lo mismo",
)
check("la CMN deja media cero", abs(fbank.cmn(f).mean(axis=0)).max() < 1e-4)

print("\n=== Embedding ===")
v = embedder.embed(tono)
check("512 dimensiones", v.shape == (embedder.EMBEDDING_DIM,), str(v.shape))
check("norma 1", abs(np.linalg.norm(v) - 1.0) < 1e-5)
check("determinista", np.allclose(v, embedder.embed(tono)))
check(
    "el mismo audio da similitud 1",
    abs(embedder.similarity(v, embedder.embed(tono)) - 1.0) < 1e-5,
)
try:
    embedder.embed(np.zeros(int(SR * 0.3)))
    check("audio demasiado corto -> error", False)
except ValueError as e:
    check("audio demasiado corto -> error", True, str(e)[:60])

print("\n=== Robustez a nivel y a ruido ===")
real = sorted(Path("datos_replay").glob("*_genuino.wav"))
if real:
    base = pipeline.load_audio(real[0].read_bytes())
    v0 = embedder.embed(base)
    check(
        "bajar el volumen 20 dB no cambia el locutor",
        embedder.similarity(v0, embedder.embed(base * 0.1)) > 0.95,
        f"{embedder.similarity(v0, embedder.embed(base * 0.1)):.3f}",
    )
    ruido = base + rng.normal(0, np.abs(base).std() * 0.1, len(base))
    check(
        "ruido a -20 dB no cambia el locutor",
        embedder.similarity(v0, embedder.embed(ruido)) > 0.85,
        f"{embedder.similarity(v0, embedder.embed(ruido)):.3f}",
    )
else:
    print("  (omitido: no hay grabaciones propias, son datos fuera de git)")

print("\n=== Separacion de locutores con datos reales ===")
print("  El unico locutor humano disponible es el de datos_replay/. Los de")
print("  scripts/ son sinteticos y salen 0.47-0.80 ENTRE SI: para el modelo son")
print("  casi el mismo hablante, porque es el mismo sintetizador. No cuentan como")
print("  tres personas y no se usan como impostores.")

if len(real) >= 2:
    E = np.array([embedder.embed(pipeline.load_audio(p.read_bytes())) for p in real])
    genuino = (E @ E.T)[np.triu_indices(len(E), 1)]
    otros = []
    for grupo in ("A", "B", "C"):
        paths = sorted(Path("scripts").glob(f"{grupo}_*.wav"))
        if paths:
            O = np.array([embedder.embed(pipeline.load_audio(p.read_bytes())) for p in paths])
            otros.append((E @ O.T).ravel())
    umbral = settings.voice_embedding_threshold
    check(
        "todas las tomas del mismo hablante superan el umbral",
        genuino.min() >= umbral,
        f"minimo {genuino.min():.3f} frente a umbral {umbral}",
    )
    if otros:
        impostor = np.concatenate(otros)
        check(
            "ningun audio ajeno supera el umbral",
            impostor.max() < umbral,
            f"maximo {impostor.max():.3f} frente a umbral {umbral}",
        )
        check(
            "hay margen entre genuino e impostor",
            genuino.min() - impostor.max() > 0.15,
            f"margen {genuino.min() - impostor.max():+.3f}",
        )
else:
    print("  (omitido: hacen falta 2+ grabaciones propias)")

print("\n  RECORDATORIO: esto NO mide FAR contra impostores humanos, porque solo")
print("  hay un hablante real disponible. Registra 3+ personas reales y mide con")
print("  scripts/diagnose_voice_db.py antes de confiar en el umbral.")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
