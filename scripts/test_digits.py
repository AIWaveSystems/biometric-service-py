import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.voice import pipeline

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += bool(condition)
    fail += not condition


SR = pipeline.SAMPLE_RATE
_rng = np.random.default_rng(0)


def tono(f0, dur=0.35):
    t = np.arange(int(SR * dur)) / SR
    sig = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6))
    return sig * np.hanning(len(t)) * 0.5


def silencio(dur):
    return _rng.normal(0, 0.0008, int(SR * dur))


print("=== Troceo por silencios ===")
x = np.concatenate([silencio(0.4)] + sum([[tono(120 + 40 * i), silencio(0.35)] for i in range(5)], []))
check("5 locuciones separadas -> 5 segmentos", len(pipeline.split_utterance(x)[0]) == 5)

pegado = np.concatenate([silencio(0.4)] + [tono(120 + 40 * i) for i in range(5)] + [silencio(0.4)])
check(
    "5 locuciones SIN pausa -> no se trocean en 5",
    len(pipeline.split_utterance(pegado)[0]) != 5,
    f"{len(pipeline.split_utterance(pegado)[0])} segmentos",
)

corto = np.concatenate([silencio(0.4), tono(200, 0.05), silencio(0.4), tono(300), silencio(0.4)])
check(
    "una locucion demasiado breve se descarta",
    len(pipeline.split_utterance(corto)[0]) == 1,
    f"{len(pipeline.split_utterance(corto)[0])} segmentos",
)

ruidoso = np.concatenate(
    [_rng.normal(0, 0.02, int(SR * 0.4))]
    + sum([[tono(120 + 40 * i), _rng.normal(0, 0.02, int(SR * 0.35))] for i in range(4)], [])
)
check(
    "con ruido de fondo el troceo sigue dando 4",
    len(pipeline.split_utterance(ruidoso)[0]) == 4,
    f"{len(pipeline.split_utterance(ruidoso)[0])} segmentos",
)

print("\n=== El desafio no acepta la respuesta a otro desafio ===")
from backend.database import Base, SessionLocal, engine
from backend.models import VoiceChallenge
from backend.security import ChallengeStore

Base.metadata.create_all(engine)

# Los desafios viven en la base, asi que sobreviven a un reinicio y funcionan con
# varios workers. La prueba usa un titular propio y borra sus filas al salir.
TITULAR = "_prueba_desafio_"
db = SessionLocal()
try:
    store = ChallengeStore(ttl_seconds=60)
    token, _ = store.issue(db, TITULAR, ("3", "7", "1", "9"))
    check(
        "un desafio emitido se consume una vez",
        store.consume(db, token, TITULAR) == ("3", "7", "1", "9"),
    )
    check("el mismo desafio NO vale dos veces", store.consume(db, token, TITULAR) is None)

    token, _ = store.issue(db, TITULAR, ("1", "2", "3", "4"))
    check("otro usuario no puede consumir mi desafio", store.consume(db, token, "otro") is None)
    check(
        "y tras el intento fallido el desafio ya no sirve",
        store.consume(db, token, TITULAR) is None,
    )

    caducado = ChallengeStore(ttl_seconds=0)
    token, _ = caducado.issue(db, TITULAR, ("1", "2"))
    check("un desafio caducado no se consume", caducado.consume(db, token, TITULAR) is None)

    token, _ = store.issue(db, TITULAR, ("5", "6"))
    otra = SessionLocal()
    try:
        check(
            "se ve desde OTRA conexion (por eso sirve con varios workers)",
            ChallengeStore(ttl_seconds=60).consume(otra, token, TITULAR) == ("5", "6"),
        )
    finally:
        otra.close()
finally:
    db.query(VoiceChallenge).filter(VoiceChallenge.username == TITULAR).delete()
    db.commit()
    db.close()

print("\n=== Discriminacion de contenido (misma toma) ===")
print("  Mide si el GMM por segmento distingue locuciones distintas del MISMO")
print("  locutor. Es una cota OPTIMISTA: entrena y prueba con frames de la misma")
print("  grabacion, asi que no incluye la desviacion de canal entre sesiones.")

fuentes = sorted(Path("datos_replay").glob("*_genuino.wav")) + sorted(
    Path("datos_digitos").glob("*.wav")
)
segmentos = []
for path in fuentes:
    audio = pipeline.load_audio(path.read_bytes())
    for seg in pipeline.split_utterance(audio)[0]:
        if len(seg) >= 40:
            segmentos.append((f"{path.stem}#{len(segmentos)}", seg))

if len(segmentos) >= 4:
    modelos = {name: pipeline.fit_digit_gmm(seg[0::2]) for name, seg in segmentos}
    aciertos = 0
    margenes = []
    for name, seg in segmentos:
        got, margin = pipeline.classify_digit(seg[1::2], modelos)
        aciertos += got == name
        margenes.append(margin)
    check(
        f"clasifica {len(segmentos)} locuciones por contenido",
        aciertos == len(segmentos),
        f"{aciertos}/{len(segmentos)} aciertos, margen minimo {min(margenes):.3f}",
    )
else:
    print("  (omitido: hacen falta grabaciones propias, son datos fuera de git)")

print("\n=== Discriminacion entre sesiones (la que cuenta) ===")
print("  Entrena con una matricula y prueba con OTRA grabada aparte. Esta es la")
print("  cifra real: incluye el cambio de canal, de nivel y de pronunciacion.")
print("  Graba dos veces:  python scripts/record_digits.py <usuario>")

matriculas = sorted(Path("datos_digitos").glob("*_matricula_*.wav"))
por_usuario: dict[str, list[Path]] = {}
for path in matriculas:
    por_usuario.setdefault(path.stem.split("_matricula_")[0], []).append(path)

evaluados = 0
for usuario, paths in por_usuario.items():
    if len(paths) < 2:
        continue
    evaluados += 1
    tomas = []
    for path in paths:
        segs = pipeline.split_utterance(pipeline.load_audio(path.read_bytes()))[0]
        if len(segs) == len(pipeline.DIGITS):
            tomas.append(dict(zip(pipeline.DIGITS, segs)))
    if len(tomas) < 2:
        print(f"  {usuario}: alguna toma no se trocea en 10, no se puede evaluar")
        continue

    aciertos = 0
    total = 0
    margenes = []
    for i, train in enumerate(tomas):
        modelos = {d: pipeline.fit_digit_gmm(s) for d, s in train.items()}
        for j, test in enumerate(tomas):
            if i == j:
                continue
            for digito, seg in test.items():
                got, margin = pipeline.classify_digit(seg, modelos)
                aciertos += got == digito
                margenes.append(margin if got == digito else -margin)
                total += 1
    tasa = aciertos / total
    fallo_desafio = 1.0 - tasa ** settings_digits if (settings_digits := 4) else 0.0
    check(
        f"{usuario}: acierto por digito entre sesiones",
        tasa >= 0.90,
        f"{aciertos}/{total} = {tasa:.1%}  ->  un desafio de 4 digitos fallaria "
        f"{fallo_desafio:.1%} de las veces con max_errors=0",
    )

if evaluados == 0:
    print("  (omitido: hacen falta 2 matriculas del mismo usuario en datos_digitos/)")

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
