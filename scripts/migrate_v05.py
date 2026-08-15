import sys
import uuid as uuid_mod
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from backend.database import Base, SessionLocal, engine
from backend.models import ApiClient, FaceTemplate, PortalUser, User  # noqa: F401
from backend.routers.portal import ensure_bootstrap_user


def column_exists(table: str, column: str) -> bool:
    return column in {c["name"] for c in inspect(engine).get_columns(table)}


def add_uuid_column(table: str) -> None:
    if column_exists(table, "uuid"):
        print(f"  {table}.uuid: ya existe")
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN uuid UUID"))
        rows = conn.execute(text(f"SELECT id FROM {table}")).fetchall()
        for row in rows:
            conn.execute(
                text(f"UPDATE {table} SET uuid = :u WHERE id = :i"),
                {"u": str(uuid_mod.uuid4()), "i": row[0]},
            )
        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN uuid SET NOT NULL"))
        conn.execute(
            text(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_uuid ON {table} (uuid)")
        )
    print(f"  {table}.uuid: creada y poblada ({len(rows)} filas)")


def drop_legacy_face_templates() -> None:
    db = SessionLocal()
    try:
        removed = (
            db.query(FaceTemplate).filter(FaceTemplate.algorithm != "sface").delete(
                synchronize_session=False
            )
        )
        db.commit()
    finally:
        db.close()
    if removed:
        print(f"  plantillas LBPH eliminadas: {removed}")
        print("  AVISO: esos usuarios deben volver a registrar la cara.")
    else:
        print("  plantillas LBPH: ninguna")


def main() -> int:
    print("1. Creando tablas nuevas (portal_users, api_clients)...")
    Base.metadata.create_all(bind=engine)

    print("2. Anadiendo columna uuid a users...")
    add_uuid_column("users")

    print("3. Retirando plantillas faciales del algoritmo antiguo...")
    drop_legacy_face_templates()

    print("4. Creando usuario inicial de portal desde .env si hace falta...")
    db = SessionLocal()
    try:
        ensure_bootstrap_user(db)
        count = db.query(PortalUser).count()
    finally:
        db.close()
    print(f"  usuarios de portal: {count}")

    print("\nMigracion completada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
