import sys
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.voice import pipeline


def load_dataset(root: Path) -> dict[str, list[Path]]:
    speakers: dict[str, list[Path]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        wavs = sorted(folder.glob("*.wav"))
        if len(wavs) >= 2:
            speakers[folder.name] = wavs
    return speakers


def features(path: Path) -> np.ndarray | None:
    try:
        return pipeline.extract_features(pipeline.load_audio(path.read_bytes()))[0]
    except ValueError as e:
        print(f"  aviso: {path.name} descartado ({e})")
        return None


def equal_error_rate(genuine: list[float], impostor: list[float]) -> tuple[float, float]:
    if not genuine or not impostor:
        return float("nan"), float("nan")
    candidates = sorted(set(genuine + impostor))
    best = (float("inf"), float("nan"), float("nan"))
    for threshold in candidates:
        frr = sum(1 for g in genuine if g < threshold) / len(genuine)
        far = sum(1 for i in impostor if i >= threshold) / len(impostor)
        if abs(far - frr) < best[0]:
            best = (abs(far - frr), threshold, (far + frr) / 2)
    return best[1], best[2]


def report(name: str, genuine: list[float], impostor: list[float], suggested: float) -> None:
    print(f"\n--- {name} ---")
    if not genuine or not impostor:
        print("  datos insuficientes")
        return
    print(f"  genuinos  n={len(genuine):<4} min={min(genuine):8.3f} media={np.mean(genuine):8.3f}")
    print(f"  impostores n={len(impostor):<4} max={max(impostor):8.3f} media={np.mean(impostor):8.3f}")
    threshold, eer = equal_error_rate(genuine, impostor)
    print(f"  umbral EER={threshold:.3f}  EER={eer * 100:.1f}%")
    frr = sum(1 for g in genuine if g < suggested) / len(genuine)
    far = sum(1 for i in impostor if i >= suggested) / len(impostor)
    print(f"  con umbral actual {suggested:.3f} -> FRR={frr * 100:.1f}%  FAR={far * 100:.1f}%")


def main(root: Path) -> None:
    speakers = load_dataset(root)
    if len(speakers) < 2:
        print(f"Se necesitan al menos 2 carpetas de locutor con 2+ WAV cada una en {root}")
        print("Estructura esperada:  datos_voz/<usuario>/<toma>.wav")
        return

    print(f"Locutores: {', '.join(f'{k} ({len(v)} tomas)' for k, v in speakers.items())}")

    feats = {}
    for name, paths in speakers.items():
        loaded = [f for f in (features(p) for p in paths) if f is not None]
        if len(loaded) >= 2:
            feats[name] = loaded

    if len(feats) < 3:
        print("\nAviso: con menos de 3 locutores el UBM no es representativo.")

    llr_gen, llr_imp = [], []
    z_gen, z_imp = [], []
    for name, takes in feats.items():
        background = [t for other, ts in feats.items() if other != name for t in ts]
        ubm = pipeline.fit_ubm(background)
        model, mean, sigma = pipeline.enroll(takes[0])
        adapted = ubm.map_adapt(takes[0], relevance=pipeline.MAP_RELEVANCE) if ubm else None

        for other, other_takes in feats.items():
            probes = other_takes[1:] if other == name else other_takes
            for probe in probes:
                _, z, _, _ = pipeline.voice_service.verify(model, mean, sigma, None, probe)
                (z_gen if other == name else z_imp).append(z)
                if adapted is not None:
                    llr = pipeline.voice_service.verify_ubm(adapted, ubm, probe)
                    (llr_gen if other == name else llr_imp).append(llr)

    report("LLR contra UBM (VOICE_LLR_THRESHOLD)", llr_gen, llr_imp, 1.2)
    report("z-score, modo reserva (VOICE_Z_THRESHOLD)", z_gen, z_imp, -2.5)
    print("\nCopia el umbral EER del LLR a VOICE_LLR_THRESHOLD en tu .env.")
    print("Para un portal, subelo por encima del EER: prioriza FAR bajo sobre comodidad.")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "datos_voz"))
