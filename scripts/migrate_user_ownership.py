import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from backend.database import engine


def main() -> int:
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "api_client_id" in columns:
        print("users.api_client_id: ya existe")
        return 0

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN api_client_id INTEGER NULL"))
        connection.execute(
            text(
                "ALTER TABLE users ADD CONSTRAINT fk_users_api_client "
                "FOREIGN KEY (api_client_id) REFERENCES api_clients(id)"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_users_api_client_id ON users (api_client_id)")
        )

    print("users.api_client_id: creada como nullable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
