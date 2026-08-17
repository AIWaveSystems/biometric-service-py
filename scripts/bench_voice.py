import sys
import time

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.voice import pipeline
from scripts.synth import make_speaker, synthesize_utterance

N_SPEAKERS = 12
N_TAKES = 4
SR = 16000

CONDITIONS = [
    {"noise_level": 0.00, "gain": 1.00, "channel": 0.00},
    {"noise_level": 0.05, "gain": 0.55, "channel": 0.35},
    {"noise_level": 0.12, "gain": 1.00, "channel": -0.25},
    {"noise_level": 0.03, "gain": 0.30, "channel": 0.60},
]


def build_corpus(seed: int = 7) -> dict[str, list[np.ndarray]]:
    rng = np.random.default_rng(seed)
    corpus = {}
    for i in range(N_SPEAKERS):
        speaker = make_speaker(i, rng)
        takes = []
        for t in range(N_TAKES):
            signal = synthesize_utterance(
                speaker, seed=1000 * i + t, duration=4.0, sr=SR, **CONDITIONS[t]
            )
            try:
                takes.append(pipeline.extract_features(signal)[0])
            except ValueError as e:
                print(f"  aviso: locutor {i} toma {t} descartada ({e})")
        if len(takes) == N_TAKES:
            corpus[f"spk{i:02d}"] = takes
    return corpus


def equal_error_rate(genuine: list[float], impostor: list[float]) -> tuple[float, float]:
    if not genuine or not impostor:
        return float("nan"), float("nan")
    best = (float("inf"), float("nan"), float("nan"))
    for threshold in sorted(set(genuine + impostor)):
        frr = sum(1 for g in genuine if g < threshold) / len(genuine)
        far = sum(1 for i in impostor if i >= threshold) / len(impostor)
        if abs(far - frr) < best[0]:
            best = (abs(far - frr), threshold, (far + frr) / 2)
    return best[1], best[2]


def summarize(name: str, genuine: list[float], impostor: list[float]) -> float:
    threshold, eer = equal_error_rate(genuine, impostor)
    print(
        f"  {name:<22} EER={eer * 100:5.1f}%  umbral={threshold:8.3f}  "
        f"genuino_med={np.mean(genuine):7.2f}  impostor_med={np.mean(impostor):7.2f}"
    )
    return eer


def evaluate(corpus: dict[str, list[np.ndarray]], method: str) -> dict[str, float]:
    names = list(corpus)
    z_gen, z_imp, r_gen, r_imp, f_gen, f_imp = [], [], [], [], [], []

    for target in names:
        enroll_feat = corpus[target][0]
        background = [corpus[o][0] for o in names if o != target]

        if method == "gmm":
            model, mean, sigma = pipeline.enroll(enroll_feat)
            cohort = pipeline.voice_service.cohort_gmm(background)
        else:
            ubm = pipeline.fit_ubm(background)
            model, mean, sigma = pipeline.enroll_map(enroll_feat, ubm)
            cohort = ubm

        for other in names:
            probes = corpus[other][1:] if other == target else corpus[other][1:2]
            for probe in probes:
                _, z, ratio, _ = pipeline.voice_service.verify(
                    model, mean, sigma, cohort, probe
                )
                fused = z + 0.5 * (ratio if ratio is not None else 0.0)
                if other == target:
                    z_gen.append(z)
                    r_gen.append(ratio)
                    f_gen.append(fused)
                else:
                    z_imp.append(z)
                    r_imp.append(ratio)
                    f_imp.append(fused)

    print(f"\n=== {method.upper()} ===")
    return {
        "z": summarize("z-score", z_gen, z_imp),
        "ratio": summarize("ratio de cohorte", r_gen, r_imp),
        "fusion": summarize("fusion z + 0.5*ratio", f_gen, f_imp),
    }


def main() -> None:
    print(f"Generando corpus: {N_SPEAKERS} locutores x {N_TAKES} tomas...")
    t0 = time.perf_counter()
    corpus = build_corpus()
    print(f"Listo en {time.perf_counter() - t0:.1f}s. Locutores validos: {len(corpus)}")
    frames = [len(f) for takes in corpus.values() for f in takes]
    print(f"Frames por toma: min={min(frames)} media={np.mean(frames):.0f} max={max(frames)}")

    methods = ["gmm"]
    if hasattr(pipeline, "fit_ubm"):
        methods.append("map")

    results = {m: evaluate(corpus, m) for m in methods}

    if len(methods) > 1:
        print("\n=== COMPARATIVA (EER, menor es mejor) ===")
        print(f"  {'estadistico':<22}{'GMM':>10}{'UBM-MAP':>10}{'mejora':>10}")
        for key in ("z", "ratio", "fusion"):
            a, b = results["gmm"][key] * 100, results["map"][key] * 100
            print(f"  {key:<22}{a:9.1f}%{b:9.1f}%{a - b:+9.1f}pp")


if __name__ == "__main__":
    main()
