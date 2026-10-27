"""Настройки проекта, значения читаются из переменных окружения."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "dev-insecure-key-change-me-in-production",
)
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],web")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "django_vite",
    "accounts",
    "rooms",
    "dictionary",
    "pipeline",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

REDIS_URL = os.environ.get("REDIS_URL", "")

if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    # Допустимо для локальной разработки; в Docker и проде задан REDIS_URL.
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }

# Кэш используется для rate limit (перебор кода комнаты, чат, фразы).
# С Redis счётчики общие для всех процессов; без него — локальный кэш процесса.
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "gluho-nemye",
        }
    }

# Ограничение перебора кода комнаты: попыток за окно на IP.
JOIN_RATE_LIMIT_ATTEMPTS = int(os.environ.get("JOIN_RATE_LIMIT_ATTEMPTS", "10"))
JOIN_RATE_LIMIT_WINDOW = int(os.environ.get("JOIN_RATE_LIMIT_WINDOW", "60"))

# Ограничение чата: сообщений за окно на участника.
CHAT_RATE_LIMIT_MESSAGES = int(os.environ.get("CHAT_RATE_LIMIT_MESSAGES", "5"))
CHAT_RATE_LIMIT_WINDOW = int(os.environ.get("CHAT_RATE_LIMIT_WINDOW", "5"))

# Heartbeat WebSocket: клиент шлёт ping раз в ROOM_PING_INTERVAL секунд,
# сервер закрывает соединение без ping за ROOM_PING_TIMEOUT секунд (ТЗ 7.6).
ROOM_PING_INTERVAL = int(os.environ.get("ROOM_PING_INTERVAL", "20"))
ROOM_PING_TIMEOUT = int(os.environ.get("ROOM_PING_TIMEOUT", "60"))

# Загрузка клипа жеста (формат — docs/spec/clip-format.md). Ограничения
# защищают хранилище от битых и слишком больших файлов.
CLIP_VERSION = int(os.environ.get("CLIP_VERSION", "1"))
CLIP_MAX_SIZE_BYTES = int(os.environ.get("CLIP_MAX_SIZE_BYTES", str(2 * 1024 * 1024)))
CLIP_MAX_FRAMES = int(os.environ.get("CLIP_MAX_FRAMES", "300"))
CLIP_DEFAULT_FPS = int(os.environ.get("CLIP_DEFAULT_FPS", "30"))

DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get(
            "DATABASE_URL",
            "postgres://app:app@localhost:5432/app",
        ),
        conn_max_age=60,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DJANGO_VITE = {
    "default": {
        "dev_mode": env_bool("DJANGO_VITE_DEV_MODE", DEBUG),
        "dev_server_host": os.environ.get("DJANGO_VITE_DEV_SERVER_HOST", "localhost"),
        "dev_server_port": int(os.environ.get("DJANGO_VITE_DEV_SERVER_PORT", "5173")),
        "static_url_prefix": "dist",
        "manifest_path": BASE_DIR / "static" / "dist" / "manifest.json",
    }
}

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

# VRM-модель аватара (C1). Пусто — тестовая страница откроется без модели:
# файл модели выбирает человек (ТЗ 15.3), URL задаётся здесь или в поле на странице.
AVATAR_MODEL_URL = os.environ.get("AVATAR_MODEL_URL", "")

# Модель MediaPipe Holistic для инструмента записи (D1). По умолчанию — официальная
# float16-модель Google; для офлайна укажите URL своего файла .task.
MEDIAPIPE_HOLISTIC_MODEL_URL = os.environ.get(
    "MEDIAPIPE_HOLISTIC_MODEL_URL",
    "https://storage.googleapis.com/mediapipe-models/holistic_landmarker/"
    "holistic_landmarker/float16/1/holistic_landmarker.task",
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

# Caddy (или прокси университета) завершает HTTPS и передаёт исходную схему.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if DEBUG:
    # В разработке и тестах манифеста ещё нет: отдаём статику как есть.
    STORAGES["staticfiles"] = {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
