# Installation

## Requirements

| Component | Version | Note |
| --- | --- | --- |
| Python | 3.11 or newer | PEP 604 `X \| None` syntax is used |
| PostgreSQL | 13 or newer | SQLite also works for local testing |
| RAM | 2 GB minimum | ONNX models are loaded into memory once |

No GPU required. All inference runs on CPU through `onnxruntime`.

---

## 1. Virtual environment and dependencies

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

## 2. Download the ONNX models

Models do not ship with the repository. They are downloaded into
`backend/biometrics/*/models/`, which is in `.gitignore`.

```bash
python scripts/fetch_models.py
```

Four files are downloaded:

| File | Purpose | Size |
| --- | --- | --- |
| `face_detection_yunet_2023mar.onnx` | Detect the face in the image | 232 KB |
| `face_recognition_sface_2021dec.onnx` | 128-dimension face embedding | 38.7 MB |
| `face_landmarks_osf.onnx` | Facial landmarks for blink measurement | 13.5 MB |
| `speaker_resnet34.onnx` | 256-dimension speaker embedding | 26.5 MB |

!!! failure "Without the face models the service will not start"
    Startup checks that they exist and raises `RuntimeError` if they are missing. The voice
    model is optional at startup, but without it speaker verification falls back to a much
    less accurate legacy path (MFCC + GMM). Always download all of them.

The script verifies the exact size of each download and prints its `sha256`, so a truncated
download is caught immediately.

---

## 3. Create the database

```bash
python scripts/create_db.py
```

Tables are created automatically on first startup via `Base.metadata.create_all`. This
script only creates the database itself if it does not exist yet.

If you are upgrading from an earlier version, run the migrations in order:

```bash
python scripts/migrate_v05.py
python scripts/migrate_voice.py
python scripts/migrate_digits.py
```

---

## 4. Configure the environment

```bash
cp .env.example .env
```

Fill in at least these four variables, without which the service will not start:

```ini
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/auth-biometric
JWT_SECRET=
PORTAL_USER=admin
PORTAL_PASSWORD=
```

Generate the secret like this:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Every variable is documented in [Configuration](configuracion.md).

---

## 5. Start the service

```bash
uvicorn backend.main:app --reload --port 8000
```

| Path | Contents |
| --- | --- |
| `http://localhost:8000/` | Test and administration portal |
| `http://localhost:8000/health` | Service and database status |
| `http://localhost:8000/docs` | Interactive OpenAPI (Basic Auth protected) |
| `http://localhost:8000/redoc` | OpenAPI reference in ReDoc format |

`/docs`, `/redoc` and `/openapi.json` require `DOCS_USER` and `DOCS_PASSWORD`; if those are
empty they inherit the portal credentials.

---

## Verify everything works

```bash
python scripts/test_full_api.py
python scripts/test_liveness.py
python scripts/test_voice.py
python scripts/test_digits.py
python scripts/test_apikeys.py
python scripts/test_speaker_embedding.py
```

Each script uses whichever instance is listening, and finishes with a count of passed and
failed checks.

!!! tip "Port already in use"
    If an earlier `uvicorn` is still alive, the tests fail for no apparent reason. On
    Windows: `netstat -ano | findstr :8010` and then `taskkill /PID <pid> /F`.
