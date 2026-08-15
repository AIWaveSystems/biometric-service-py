import sys

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.voice import pipeline, wav
from scripts.synth import synthesize_speaker

SPEAKERS = [("A", 110.0, 0.9), ("B", 180.0, 0.5), ("C", 240.0, 0.3)]
Z_THRESHOLD = -2.5
RATIO_THRESHOLD = -3.0

ok = 0
fail = 0


def check(label, condition, extra=""):
    global ok, fail
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  ({extra})" if extra else ""))
    ok += condition
    fail += not condition


for name, f0, formant in SPEAKERS:
    for seed in (1, 2, 3):
        signal = synthesize_speaker(f0, seed=seed, formant=formant)
        with open(f"scripts/{name}_{seed}.wav", "wb") as handle:
            handle.write(wav.write_wav(signal, 16000))


def load(name):
    out = []
    for seed in (1, 2, 3):
        raw, sr = wav.read_wav(open(f"scripts/{name}_{seed}.wav", "rb").read())
        out.append(pipeline.extract_features(wav.resample(raw, sr, pipeline.SAMPLE_RATE))[0])
    return out


features = {name: load(name) for name, _, _ in SPEAKERS}

print("=== Matricula y calibracion ===")
models = {}
for name in features:
    enroll_feat = features[name][0]
    model, mean, sigma = pipeline.enroll(enroll_feat)
    models[name] = (model, mean, sigma)
    train_score = model.mean_score(enroll_feat)
    print(f"  {name}: {len(enroll_feat)} frames, k={model.n_components}")
    print(f"     entrenamiento={train_score:7.2f}  held-out={mean:7.2f}  sigma={sigma:.2f}")
    check(f"{name}: held-out por debajo del entrenamiento", mean < train_score)

print("\n=== Verificacion (z-score + ratio de cohorte) ===")
for target in features:
    model, mean, sigma = models[target]
    cohort = pipeline.voice_service.cohort_gmm(
        [f for other, fs in features.items() if other != target for f in fs]
    )
    for probe_name in features:
        for probe in features[probe_name][1:]:
            _, z, ratio, _ = pipeline.voice_service.verify(model, mean, sigma, cohort, probe)
            accepted = z >= Z_THRESHOLD and (ratio is None or ratio >= RATIO_THRESHOLD)
            genuine = probe_name == target
            check(
                f"locutor {probe_name} contra modelo {target} -> {'acepta' if genuine else 'rechaza'}",
                accepted == genuine,
                f"z={z:.2f} ratio={ratio:.2f}",
            )

print(f"\nRESULTADO: {ok} pasaron, {fail} fallaron")
sys.exit(1 if fail else 0)
