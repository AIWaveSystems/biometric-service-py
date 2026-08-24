import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from backend.database import Base, SessionLocal, engine
from backend.models import User, VoiceDigitTemplate  # noqa: F401


def main() -> int:
    before = set(inspect(engine).get_table_names())
    print("Creando la tabla voice_digit_templates si no existe...")
    Base.metadata.create_all(bind=engine)
    after = set(inspect(engine).get_table_names())

    created = sorted(after - before)
    print(f"  tablas creadas: {', '.join(created) if created else 'ninguna (ya estaba)'}")

    # La normalizacion de la matricula se guarda desde la version que corrige el
    # sesgo de CMVN entre una toma de 10 digitos y un desafio de 4. Las matriculas
    # anteriores se quedan con cmvn NULL y siguen funcionando por el camino viejo.
    cols = {c["name"] for c in inspect(engine).get_columns("voice_digit_templates")}
    if "cmvn" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE voice_digit_templates ADD COLUMN cmvn BYTEA"))
        print("  columna cmvn: creada")
    else:
        print("  columna cmvn: ya existe")

    # Embedding de locutor (CAM++). Las plantillas de voz anteriores quedan con
    # embedding NULL y siguen verificando por MFCC+GMM hasta que se re-registren.
    vcols = {c["name"] for c in inspect(engine).get_columns("voice_templates")}
    if "embedding" not in vcols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE voice_templates ADD COLUMN embedding BYTEA"))
        print("  columna embedding: creada")
    else:
        print("  columna embedding: ya existe")

    db = SessionLocal()
    try:
        users = db.query(User).count()
        digits = db.query(VoiceDigitTemplate).count()
    finally:
        db.close()

    print(f"  usuarios existentes: {users} (intactos)")
    print(f"  digitos matriculados: {digits}")
    print("\nMigracion completada. Ningun dato existente se ha modificado.")
    print("Los usuarios ya registrados siguen usando /api/voice/verify sin cambios;")
    print("para el desafio de digitos deben matricularlos con /api/voice/digits/enroll.")
    print("\nPara que usen el modelo de locutor nuevo (mucho mas preciso) hay que")
    print("volver a registrar su voz: el embedding se calcula al matricular.")
    print("Comprueba quien lo tiene ya con: python scripts/diagnose_voice_db.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
