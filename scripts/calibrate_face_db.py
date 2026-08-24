import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sqlalchemy import select

from backend.biometrics.face.embedder import similarity
from backend.config import settings
from backend.database import SessionLocal
from backend.models import FaceTemplate, User

TARGET_FARS = (0.01, 0.001, 0.0001)
SWEEP = (0.30, 0.35, 0.363, 0.40, 0.45, 0.50)
TOP_IMPOSTORS = 8
SUSPECT_MIN = 0.50
N_BOOTSTRAP = 2000


def load_templates(db):
    rows = db.execute(
        select(FaceTemplate.id, FaceTemplate.user_id, FaceTemplate.features, User.username)
        .join(User, User.id == FaceTemplate.user_id)
        .where(FaceTemplate.algorithm == "sface")
    ).all()
    return [
        {"id": rid, "user_id": uid, "username": name, "vector": np.frombuffer(f, dtype=np.float32)}
        for rid, uid, f, name in rows
    ]


def pairwise(templates):
    genuine, impostor = [], []
    for a, b in itertools.combinations(range(len(templates)), 2):
        ta, tb = templates[a], templates[b]
        score = float(similarity(ta["vector"], tb["vector"]))
        if ta["user_id"] == tb["user_id"]:
            genuine.append(score)
        else:
            impostor.append((score, ta["username"], tb["username"], ta["id"], tb["id"]))
    return genuine, impostor


def equal_error_rate(genuine, impostor_scores):
    candidates = sorted(set(genuine) | set(impostor_scores))
    best = (float("inf"), float("nan"), float("nan"))
    for t in candidates:
        frr = sum(1 for g in genuine if g < t) / len(genuine)
        far = sum(1 for i in impostor_scores if i >= t) / len(impostor_scores)
        if abs(far - frr) < best[0]:
            best = (abs(far - frr), t, (far + frr) / 2)
    return best[1], best[2]


def bootstrap_threshold_ci(scores, q, n_boot=N_BOOTSTRAP, seed=0):
    rng = np.random.default_rng(seed)
    arr = np.asarray(scores, dtype=np.float64)
    samples = rng.choice(arr, size=(n_boot, arr.size), replace=True)
    thresholds = np.quantile(samples, q, axis=1)
    return float(np.quantile(thresholds, 0.025)), float(np.quantile(thresholds, 0.975))


def main():
    excluir = "--excluir-sospechosos" in sys.argv
    db = SessionLocal()
    try:
        templates = load_templates(db)
    finally:
        db.close()

    users = sorted({t["username"] for t in templates})
    print(f"\nPlantillas sface: {len(templates)} de {len(users)} usuario(s)")
    if len(users) < 2 or len(templates) < 4:
        print("Se necesitan 2+ usuarios con plantillas para separar genuinos de impostores.")
        return

    genuine, impostor = pairwise(templates)
    suspects = sorted((p for p in impostor if p[0] >= SUSPECT_MIN), reverse=True)
    if suspects and excluir:
        print(f"\nExcluidos {len(suspects)} par(es) sospechosos de cuentas gemelas (>={SUSPECT_MIN}):")
        for score, ua, ub, ia, ib in suspects[:TOP_IMPOSTORS]:
            print(f"    {score:.4f}  {ua} (#{ia}) vs {ub} (#{ib})")
        impostor = [p for p in impostor if p[0] < SUSPECT_MIN]
    elif suspects:
        print(
            f"\nHay {len(suspects)} par(es) impostores con similitud >={SUSPECT_MIN} "
            "(posibles cuentas gemelas). Recalcula con --excluir-sospechosos para ver las"
        )
        print("distribuciones limpias; los numeros de abajo los incluyen y estan contaminados.")

    if not impostor:
        print("\nSin pares impostores tras el filtro: no se puede calibrar.")
        return
    impostor_scores = [s for s, *_ in impostor]

    print("\n=== PARES ENTRE PLANTILLAS GUARDADAS ===")
    print(f"  genuinos   n={len(genuine):<6} peor={min(genuine):.4f} media={np.mean(genuine):.4f}")
    print(f"  impostores n={len(impostor):<6} mejor={max(impostor_scores):.4f} media={np.mean(impostor_scores):.4f}")
    print(f"  separacion {min(genuine) - max(impostor_scores):+.4f}")

    eer_threshold, eer = equal_error_rate(genuine, impostor_scores)
    print(f"  umbral EER={eer_threshold:.4f}  EER={eer * 100:.2f}%")

    current = settings.face_threshold
    print("\n  umbral     FRR      FAR")
    for t in sorted(set(SWEEP) | {round(current, 3)}):
        frr = 100 * sum(1 for g in genuine if g < t) / len(genuine)
        far = 100 * sum(1 for s in impostor_scores if s >= t) / len(impostor_scores)
        mark = "  <- actual" if abs(t - round(current, 3)) < 1e-9 else ""
        print(f"  {t:<10.3f} {frr:6.2f}%  {far:6.2f}%{mark}")

    print("\n  umbral sugerido por FAR objetivo (impostor que iguala o supera el corte)")
    for target in TARGET_FARS:
        t = float(np.quantile(impostor_scores, 1.0 - target))
        lo, hi = bootstrap_threshold_ci(impostor_scores, 1.0 - target)
        fnmr = 100 * sum(1 for g in genuine if g < t) / len(genuine)
        print(
            f"  FAR {target * 100:>5.2f}%  ->  umbral {t:.4f} "
            f"IC95% [{lo:.4f}, {hi:.4f}]   (rechazaria {fnmr:.2f}% de genuinos)"
        )

    worst = sorted(impostor, reverse=True)[:TOP_IMPOSTORS]
    if worst and worst[0][0] >= 0.30:
        print("\n  !!! pares impostores mas altos (posibles cuentas duplicadas o gemelas):")
        for score, ua, ub, ia, ib in worst:
            flag = "  <-- cruza el umbral actual" if score >= current else ""
            print(f"    {score:.4f}  {ua} (#{ia}) vs {ub} (#{ib}){flag}")

    print("\nEl login real usa la mediana de la mitad superior de frames filtrados, no un par")
    print("aislado: estos numeros aproximan el peor caso. Repite la medicion cuando crezca")
    print("la base y aplica el cambio con FACE_THRESHOLD en el .env.")


if __name__ == "__main__":
    main()
