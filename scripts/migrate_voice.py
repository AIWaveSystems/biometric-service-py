import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from backend.database import engine

STATEMENTS = [
    "ALTER TABLE voice_templates ADD COLUMN IF NOT EXISTS self_score DOUBLE PRECISION DEFAULT 0.0",
    "ALTER TABLE voice_templates ADD COLUMN IF NOT EXISTS self_sigma DOUBLE PRECISION DEFAULT 1.0",
    "DELETE FROM voice_templates",
]


def main() -> None:
    with engine.connect() as conn:
        for statement in STATEMENTS:
            conn.execute(text(statement))
        conn.commit()
    print("OK: columnas self_score/self_sigma listas.")
    print("Las plantillas de voz se han borrado: el VAD y la calibracion cambiaron,")
    print("cada usuario debe volver a registrar su voz desde el portal.")


if __name__ == "__main__":
    main()
