# Instalacion

## Requisitos

| Componente | Version | Nota |
| --- | --- | --- |
| Python | 3.11 o superior | Se usa sintaxis `X \| None` de PEP 604 |
| PostgreSQL | 13 o superior | Tambien funciona SQLite para pruebas locales |
| RAM | 2 GB minimo | Los modelos ONNX se cargan en memoria una sola vez |

No hace falta GPU. Toda la inferencia corre en CPU con `onnxruntime`.

---

## 1. Entorno virtual y dependencias

=== "Windows (PowerShell)"

    ```powershell
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    ```

=== "Linux / macOS"

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

---

## 2. Descargar los modelos ONNX

Los modelos no viajan en el repositorio: se descargan a `backend/biometrics/*/models/`,
que esta en `.gitignore`.

```bash
python scripts/fetch_models.py
```

Descarga cinco archivos:

| Archivo | Para que sirve | Tamano |
| --- | --- | --- |
| `face_detection_yunet_2023mar.onnx` | Detectar el rostro en la imagen | 232 KB |
| `face_recognition_sface_2021dec.onnx` | Embedding facial de 128 dimensiones | 38.7 MB |
| `face_landmarks_osf.onnx` | Puntos faciales para medir el parpadeo | 13.5 MB |
| `speaker_resnet34.onnx` | Embedding de locutor de 256 dimensiones | 26.5 MB |

!!! failure "Sin los modelos faciales el servicio no arranca"
    El arranque comprueba que existan y lanza `RuntimeError` si faltan. El modelo de voz
    es opcional en el arranque, pero sin el la verificacion de locutor cae a un camino
    antiguo (MFCC + GMM) mucho menos preciso. Descargalos siempre.

El script verifica el tamano exacto de cada descarga y muestra el `sha256`, asi que una
descarga truncada se detecta en el momento.

---

## 3. Crear la base de datos

```bash
python scripts/create_db.py
```

Las tablas se crean solas en el primer arranque (`Base.metadata.create_all`). Este script
solo se encarga de crear la base si aun no existe.

Si vienes de una version anterior, ejecuta las migraciones en orden:

```bash
python scripts/migrate_v05.py
python scripts/migrate_voice.py
python scripts/migrate_digits.py
```

---

## 4. Configurar el entorno

```bash
cp .env.example .env
```

Rellena como minimo estas cuatro variables, sin las cuales el servicio no arranca:

```ini
DATABASE_URL=postgresql+psycopg2://usuario:clave@localhost:5432/auth-biometric
JWT_SECRET=
PORTAL_USER=admin
PORTAL_PASSWORD=
```

Genera el secreto asi:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

El detalle completo de cada variable esta en [Configuracion](configuracion.md).

---

## 5. Arrancar

```bash
uvicorn backend.main:app --reload --port 8000
```

| Ruta | Contenido |
| --- | --- |
| `http://localhost:8000/` | Portal de pruebas y administracion |
| `http://localhost:8000/health` | Estado del servicio y de la base |
| `http://localhost:8000/docs` | OpenAPI interactivo (protegido con Basic Auth) |
| `http://localhost:8000/redoc` | Referencia OpenAPI en formato ReDoc |

`/docs`, `/redoc` y `/openapi.json` piden `DOCS_USER` y `DOCS_PASSWORD`; si estan vacias,
heredan las credenciales del portal.

---

## Comprobar que todo funciona

```bash
python scripts/test_full_api.py
python scripts/test_liveness.py
python scripts/test_voice.py
python scripts/test_digits.py
python scripts/test_apikeys.py
python scripts/test_speaker_embedding.py
```

Cada script arranca su propia instancia o usa la que este escuchando, y termina con un
recuento de comprobaciones pasadas y fallidas.

!!! tip "Puerto ocupado"
    Si un `uvicorn` anterior sigue vivo, las pruebas fallan sin motivo aparente. En
    Windows: `netstat -ano | findstr :8010` y luego `taskkill /PID <pid> /F`.
