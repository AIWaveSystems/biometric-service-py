import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text

from backend.config import settings

OLD_INDEX = "ix_users_username"
TENANT_INDEX = "uq_users_tenant_username"
PORTAL_INDEX = "uq_users_portal_username"

DDL = [
    f"DROP INDEX IF EXISTS {OLD_INDEX}",
    f"CREATE INDEX IF NOT EXISTS {OLD_INDEX} ON users (username)",
    f"CREATE UNIQUE INDEX IF NOT EXISTS {TENANT_INDEX} ON users (api_client_id, username)",
    (
        f"CREATE UNIQUE INDEX IF NOT EXISTS {PORTAL_INDEX} ON users (username) "
        "WHERE api_client_id IS NULL"
    ),
]


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Migra la unicidad de usernames de global a por sistema cliente: "
            "UNIQUE(api_client_id, username) + username unico solo dentro del pool del portal."
        )
    )
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="URL de la base (por defecto usa DATABASE_URL del .env)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Muestra el SQL sin ejecutarlo"
    )
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    insp = inspect(engine)
    existing = {ix["name"] for ix in insp.get_indexes("users")}

    print("Indices actuales en users:", sorted(existing) or "(ninguno)")
    for stmt in DDL:
        print("SQL:", stmt)

    if args.dry_run:
        print("\nDry-run: no se ejecuto nada.")
        return

    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))

    after = {ix["name"] for ix in inspect(engine).get_indexes("users")}
    faltan = {TENANT_INDEX, PORTAL_INDEX} - after
    if faltan:
        raise SystemExit(f"ERROR: no se pudieron crear los indices: {sorted(faltan)}")
    print("\nListo. Unicidad de usernames ahora es por sistema cliente.")
    print(f"  - {TENANT_INDEX}: (api_client_id, username)")
    print(f"  - {PORTAL_INDEX}: username solo entre usuarios del portal")


if __name__ == "__main__":
    main()
