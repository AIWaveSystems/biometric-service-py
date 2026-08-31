FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY scripts/fetch_models.py ./scripts/fetch_models.py
RUN python scripts/fetch_models.py

COPY backend/ ./backend/
COPY static/ ./static/
COPY alembic.ini ./
COPY migrations/ ./migrations/

RUN python -c "from backend.biometrics.face import embedder, landmarks; from backend.biometrics.voice import embedder as speaker; assert embedder.available(), 'falta yunet o sface'; assert landmarks.available(), 'falta el modelo de landmarks'; assert speaker.available(), 'falta el modelo de locutor'; print('modelos ONNX verificados dentro de la imagen')"

RUN useradd --system --create-home --uid 10001 biometrico \
    && chown -R biometrico:biometrico /app
USER biometrico

ENV UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    UVICORN_WORKERS=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${UVICORN_PORT}/health" > /dev/null || exit 1

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn backend.main:app --host \"$UVICORN_HOST\" --port \"$UVICORN_PORT\" --workers \"$UVICORN_WORKERS\" --proxy-headers --forwarded-allow-ips='*'"]
