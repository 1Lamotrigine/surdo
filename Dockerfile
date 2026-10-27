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
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/static/dist ./static/dist

RUN SECRET_KEY=collectstatic-build \
    DEBUG=False \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/media \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
