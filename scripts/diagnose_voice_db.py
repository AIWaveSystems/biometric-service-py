import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.biometrics.voice import pipeline
from backend.config import settings
from backend.database import SessionLocal
from backend.models import User, VoiceTemplate
from backend.routers.voice import FEATURE_DIM, MIN_BACKGROUND_SPEAKERS

USO = """Reproduce, contra la base real, exactamente lo que hace /api/voice/verify.

  python scripts/diagnose_voice_db.py
      Matriz cruzada con las plantillas guardadas. Es una cota OPTIMISTA: puntua
      el audio de matricula contra el modelo construido con ese mismo audio.

  python scripts/diagnose_voice_db.py <fichero.wav | carpeta> [...]
      Puntua audio FRESCO contra TODOS los usuarios. Esta es la prueba que
      importa: si una sola toma pasa el umbral en varias cuentas, la verificacion
      no esta distinguiendo a nadie.

No escribe nada en la base.
"""


def modelos_por_usuario(plantillas: list[dict]) -> dict:
    """Un UBM por usuario (leave-one-out), igual que hace la API en cada peticion."""
    salida = {}
    for objetivo in plantillas:
        fondo = [p for p in plantillas if p["user_id"] != objetivo["user_id"]]
        locutores = {p["user_id"] for p in fondo}
        if len(locutores) >= MIN_BACKGROUND_SPEAKERS:
            ubm = pipeline.fit_ubm([p["feat"] for p in fondo])
            salida[objetivo["username"]] = (
                "ubm-map",
                ubm.map_adapt(objetivo["feat"], relevance=pipeline.MAP_RELEVANCE),
                ubm,
                objetivo,
            )
        else:
            salida[objetivo["username"]] = (
                "gmm-z",
                pipeline.deserialize_gmm(objetivo["parameters"]),
                pipeline.voice_service.cohort_gmm([p["feat"] for p in fondo]),
                objetivo,
            )
    return salida


def puntuar(modelo_info, feat: np.ndarray) -> float:
    modo, modelo, referencia, objetivo = modelo_info
    if modo == "ubm-map":
        return pipeline.voice_service.verify_ubm(modelo, referencia, feat)
    _, z, _, _ = pipeline.voice_service.verify(
        modelo, objetivo["self_score"], objetivo["self_sigma"], referencia, feat
    )
    return z


def recolectar(rutas: list[str]) -> list[Path]:
    ficheros: list[Path] = []
    for ruta in rutas:
        p = Path(ruta)
        if p.is_dir():
            ficheros += sorted(p.glob("*.wav"))
        elif p.is_file():
            ficheros.append(p)
        else:
            print(f"  aviso: no existe {p}")
    return ficheros


def probar_frescos(plantillas: list[dict], rutas: list[str]) -> int:
    ficheros = recolectar(rutas)
    if not ficheros:
        print("No se encontro ningun .wav.")
        return 1

    modelos = modelos_por_usuario(plantillas)
    nombres = [p["username"] for p in plantillas]
    modo = modelos[nombres[0]][0]
    umbral = settings.voice_llr_threshold if modo == "ubm-map" else settings.voice_z_threshold

    print(f"\nAudio fresco contra las {len(nombres)} cuentas de la base.")
    print(f"Modo: {modo}   umbral: {umbral}\n")

    ancho = max(24, max(len(f.name) for f in ficheros) + 1)
    print(" " * ancho + "".join(f"{x[:8]:>9s}" for x in nombres) + "   aceptado en")

    aceptaciones = []
    por_fichero: list[dict] = []
    for fichero in ficheros:
        try:
            feat, _ = pipeline.extract_features(pipeline.load_audio(fichero.read_bytes()))
        except ValueError as e:
            print(f"{fichero.name:<{ancho}s}  descartado: {e}")
            continue
        celdas = ""
        pasa = []
        fila_valores = {}
        for nombre in nombres:
            v = puntuar(modelos[nombre], feat)
            fila_valores[nombre] = v
            if v >= umbral:
                pasa.append(nombre)
                celdas += f"{v:8.2f}*"
            else:
                celdas += f"{v:8.2f} "
        aceptaciones.append(len(pasa))
        por_fichero.append(fila_valores)
        print(f"{fichero.name:<{ancho}s}{celdas}   {len(pasa)}: {', '.join(pasa) or '-'}")

    print("\n--- Diagnostico ---")
    if not aceptaciones:
        print("Ningun fichero pudo procesarse.")
        return 1

    mejores = [max(f.items(), key=lambda kv: kv[1]) for f in por_fichero]
    print(f"Mejor coincidencia por toma: {', '.join(f'{n}' for n, _ in mejores)}")
    if len({n for n, _ in mejores}) == 1:
        titular = mejores[0][0]
        genuinos = [f[titular] for f in por_fichero]
        impostores = [v for f in por_fichero for n, v in f.items() if n != titular]
        falsos = sum(1 for v in impostores if v >= umbral)
        print(
            f"\nTodas las tomas ganan en '{titular}', y por margen: "
            f"{min(genuinos):.2f} .. {max(genuinos):.2f}"
        )
        print(f"El resto de cuentas puntua: {min(impostores):.2f} .. {max(impostores):.2f}")
        print(f"\nCon el umbral actual ({umbral}) se aceptan {falsos}/{len(impostores)} "
              f"impostores = {falsos / len(impostores):.1%} de FAR.")
        if min(genuinos) > max(impostores):
            sugerido = round((min(genuinos) + max(impostores)) / 2, 2)
            print(
                f"\nLa IDENTIFICACION es perfecta: el titular siempre gana.\n"
                f"Lo que falla es el UMBRAL, que esta por debajo de los impostores.\n"
                f"Con VOICE_LLR_THRESHOLD={sugerido} estos datos dan 0% de FAR y 0% de FRR."
            )
        else:
            print(
                "\nNingun umbral separa: el mejor impostor puntua por encima del peor\n"
                "genuino. Hace falta mas audio de matricula, no recalibrar."
            )

    varias = sum(1 for a in aceptaciones if a > 1)
    ninguna = sum(1 for a in aceptaciones if a == 0)
    print(f"Tomas que pasan en MAS DE UNA cuenta: {varias}/{len(aceptaciones)}")
    print(f"Tomas que no pasan en ninguna:        {ninguna}/{len(aceptaciones)}")

    if varias:
        print(
            "\nUna misma toma abre varias cuentas: el sistema NO esta distinguiendo\n"
            "locutores. Si esas cuentas son de la misma persona fisica, es el\n"
            "comportamiento correcto y el problema es la base, no el algoritmo."
        )
    elif ninguna == len(aceptaciones):
        print(
            "\nNinguna toma pasa en ninguna cuenta. Si el audio es de una persona que\n"
            "NO esta registrada, esto es exactamente lo que debe pasar."
        )
    else:
        print("\nCada toma abre como mucho una cuenta.")
    return 0


def revisar_duplicados(plantillas: list[dict]) -> bool:
    """Delata dos cuentas con la MISMA voz matriculada.

    Es la causa numero uno de "el login por voz acepta a cualquiera": no falla el
    modelo, es que las dos cuentas contienen a la misma persona, asi que una sola
    grabacion abre las dos y el sistema esta acertando.
    """
    from backend.biometrics.voice import embedder

    con_emb = [(p["username"], p.get("emb")) for p in plantillas if p.get("emb") is not None]
    if len(con_emb) < 2:
        print("\n(sin embeddings suficientes para buscar cuentas duplicadas)")
        return False

    umbral = settings.voice_duplicate_threshold
    choques = []
    for i, (na, va) in enumerate(con_emb):
        for nb, vb in con_emb[i + 1 :]:
            sim = embedder.similarity(va, vb)
            if sim >= umbral:
                choques.append((na, nb, sim))

    if not choques:
        print(f"\nCuentas con la misma voz: ninguna (umbral {umbral}).")
        return False

    print(f"\n!!! CUENTAS QUE COMPARTEN VOZ (umbral {umbral}) !!!")
    for na, nb, sim in sorted(choques, key=lambda c: -c[2]):
        print(f"  {na} <-> {nb}   similitud {sim:.3f}")
    print(
        "\nUna sola grabacion abre TODAS las cuentas de cada pareja. Esto NO es un\n"
        "fallo del modelo: son la misma voz matriculada varias veces. Borra o\n"
        "regraba las cuentas sobrantes. Desde la version con guardia de duplicados,\n"
        "matricular una voz ya registrada devuelve 409."
    )
    return True


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(USO)
        return 0

    db = SessionLocal()
    try:
        rows = (
            db.query(VoiceTemplate, User.username)
            .join(User, User.id == VoiceTemplate.user_id)
            .order_by(User.username)
            .all()
        )
        plantillas = [
            {
                "username": nombre,
                "user_id": t.user_id,
                "feat": np.frombuffer(t.features, dtype=np.float32).reshape(-1, FEATURE_DIM),
                "self_score": t.self_score,
                "self_sigma": t.self_sigma,
                "parameters": t.parameters,
                "duration": t.duration_seconds,
                "emb": None if not t.embedding else np.frombuffer(t.embedding, dtype=np.float32),
            }
            for t, nombre in rows
        ]
    finally:
        db.close()

    if len(plantillas) < 2:
        print("Hacen falta al menos 2 usuarios con voz para medir nada.")
        return 1

    if revisar_duplicados(plantillas) and len(sys.argv) <= 1:
        return 1

    print(f"Plantillas de voz en la base: {len(plantillas)}")
    for p in plantillas:
        print(f"  {p['username']:14s} {p['duration']:5.1f}s  {len(p['feat']):5d} frames")

    if len(sys.argv) > 1:
        return probar_frescos(plantillas, sys.argv[1:])

    nombres = [p["username"] for p in plantillas]
    n = len(plantillas)
    matriz = np.full((n, n), np.nan)
    modos = []

    print("\nCalculando (un UBM por usuario, leave-one-out, como en produccion)...")
    for j, objetivo in enumerate(plantillas):
        fondo = [p for p in plantillas if p["user_id"] != objetivo["user_id"]]
        locutores = {p["user_id"] for p in fondo}

        if len(locutores) >= MIN_BACKGROUND_SPEAKERS:
            ubm = pipeline.fit_ubm([p["feat"] for p in fondo])
            modelo = ubm.map_adapt(objetivo["feat"], relevance=pipeline.MAP_RELEVANCE)
            modos.append("ubm-map")
            for i, prueba in enumerate(plantillas):
                matriz[i, j] = pipeline.voice_service.verify_ubm(modelo, ubm, prueba["feat"])
        else:
            modelo = pipeline.deserialize_gmm(objetivo["parameters"])
            cohorte = pipeline.voice_service.cohort_gmm([p["feat"] for p in fondo])
            modos.append("gmm-z")
            for i, prueba in enumerate(plantillas):
                _, z, _, _ = pipeline.voice_service.verify(
                    modelo, objetivo["self_score"], objetivo["self_sigma"], cohorte, prueba["feat"]
                )
                matriz[i, j] = z

    modo = modos[0] if len(set(modos)) == 1 else "mixto"
    umbral = (
        settings.voice_llr_threshold if modo == "ubm-map" else settings.voice_z_threshold
    )

    print(f"\nModo de puntuacion: {modo}   umbral: {umbral}")
    print("\nFila = quien habla.  Columna = modelo contra el que se compara.")
    print("Un valor >= umbral significa ACEPTADO.\n")

    ancho = max(10, max(len(x) for x in nombres) + 1)
    print(" " * ancho + "".join(f"{x[:8]:>9s}" for x in nombres))
    for i, fila in enumerate(nombres):
        celdas = ""
        for j in range(n):
            v = matriz[i, j]
            marca = "*" if v >= umbral else " "
            celdas += f"{v:8.2f}{marca}"
        print(f"{fila:<{ancho}s}{celdas}")
    print("\n(* = el sistema aceptaria esa combinacion)")

    diagonal = np.array([matriz[i, i] for i in range(n)])
    fuera = np.array([matriz[i, j] for i in range(n) for j in range(n) if i != j])

    aceptados = int((fuera >= umbral).sum())
    total = len(fuera)
    print(f"\nGenuinos (diagonal):  {diagonal.min():7.2f} .. {diagonal.max():7.2f}")
    print(f"Impostores (resto):   {fuera.min():7.2f} .. {fuera.max():7.2f}")
    print(f"\nIMPOSTORES ACEPTADOS: {aceptados}/{total} = {aceptados / total:.1%}")

    separacion = float(diagonal.min() - fuera.max())
    print(f"Separacion (peor genuino - mejor impostor): {separacion:.2f}")

    print("\n--- Diagnostico ---")
    if aceptados == 0:
        print("La verificacion separa a los locutores con estas plantillas.")
    elif aceptados == total:
        print("TODOS los impostores pasan. La verificacion no esta verificando nada.")
    else:
        print(f"{aceptados} de {total} impostores pasan. La verificacion es inservible tal cual.")

    if separacion <= 0:
        print(
            "El mejor impostor puntua igual o mejor que el peor genuino: NINGUN umbral\n"
            "arregla esto. No es calibracion, es que la poblacion de fondo no representa\n"
            "a 'los demas'."
        )

    print(
        "\nANTES DE CREER ESTOS NUMEROS: mira QUIEN hace de impostor.\n"
        "Un FAR bajo solo significa algo si los impostores son PERSONAS REALES\n"
        "distintas del titular. Las voces de TTS (TikTok, sintetizadores, el usuario\n"
        "que deja test_full_api.py) son mucho mas distintas entre si y del habla real\n"
        "que dos personas de verdad: la tarea sale facil y el FAR sale bonito.\n"
        "Con una poblacion sintetica este numero NO mide seguridad."
    )

    print("\nCausas habituales, en orden de probabilidad:")
    print("  1. Varios usuarios son LA MISMA PERSONA con nombres distintos.")
    print("     El UBM incluye entonces la voz del objetivo y deja de ser 'los demas'.")
    print("  2. Los locutores de fondo son SINTETICOS (TTS) y no representan a nadie.")
    print("  3. Las tomas son demasiado cortas para un GMM diagonal.")
    print("\nComprueba cuantas personas FISICAS distintas hay realmente detras de esos")
    print("nombres. Si son menos de 3, el resultado de arriba es el esperado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
