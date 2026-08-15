import psycopg2

PASSWORD = "1614"
DB_NAME = "auth-biometric"

try:
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password=PASSWORD,
        dbname="postgres",
        options="-c client_encoding=WIN1252",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB_NAME,))
    if cur.fetchone():
        print(f"{DB_NAME} ya existe")
    else:
        cur.execute(f'CREATE DATABASE "{DB_NAME}"')
        print(f"{DB_NAME} creada")
    conn.close()
except Exception as e:
    msg = str(e).encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    print("ERROR:", msg)
