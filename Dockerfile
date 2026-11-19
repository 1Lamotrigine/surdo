FROM node:22-slim AS frontend

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY tsconfig.json vite.config.ts ./
COPY frontend ./frontend
RUN npm run typecheck && npm run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Домашний каталог для кэша моделей (Whisper/VAD). У системного
    # пользователя по умолчанию HOME=/nonexistent, из-за чего faster-whisper
    # не мог скачать веса (PermissionError) и распознавание падало.
    HOME=/home/app \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache

WORKDIR /app

# CTranslate2 (движок faster-whisper) использует системный libgomp.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/static/dist ./static/dist

RUN SECRET_KEY=collectstatic-build \
    DEBUG=False \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/media /home/app/.cache/huggingface \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8000

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
