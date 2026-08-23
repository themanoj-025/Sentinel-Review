"""
Django settings for sentinel_review project.
"""

import logging
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent

# Security

_AUTO_GENERATED_KEY = get_random_secret_key()
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _AUTO_GENERATED_KEY)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

if not DEBUG:
    missing = []
    if not SECRET_KEY or SECRET_KEY == _AUTO_GENERATED_KEY:
        missing.append("DJANGO_SECRET_KEY")
    if not os.environ.get("WEBHOOK_SECRET"):
        missing.append("WEBHOOK_SECRET")
    if missing:
        raise ImproperlyConfigured(
            "Critical environment variables not set: {}. "
            "Set these in your environment or .env file.".format(", ".join(missing))
        )

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Applications

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Local
    "sentinel_review.apps.SentinelReviewConfig",
    "sentinel_review.webhooks",
    "sentinel_review.dashboard",
    "sentinel_review.api",
    "sentinel_review.workers",
]

if DEBUG:
    INSTALLED_APPS += ["django_extensions"]

# Conditionally add drf-spectacular if available
try:
    import drf_spectacular  # noqa: F401

    INSTALLED_APPS += ["drf_spectacular"]
except ImportError:
    pass

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sentinel_review.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "sentinel_review.wsgi.application"

# Database

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///{}".format(BASE_DIR / "db.sqlite3"))
DATABASES = {
    "default": dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if not DEBUG else []

# REST Framework

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "sentinel_review.api.authentication.APIKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
    },
}

# drf-spectacular (OpenAPI)
try:
    import drf_spectacular  # noqa: F401

    REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
    SPECTACULAR_SETTINGS = {
        "TITLE": "Sentinel Review API",
        "DESCRIPTION": "Automated PR review agent powered by LLMs",
        "VERSION": "1.0.0",
        "SERVE_INCLUDE_SCHEMA": False,
    }
except ImportError:
    SPECTACULAR_SETTINGS = {}

# Celery

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_RESULT_EXPIRES = 3600 * 24

# GitHub App

GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_CLIENT_ID = os.environ.get("GITHUB_APP_CLIENT_ID", "")
GITHUB_APP_CLIENT_SECRET = os.environ.get("GITHUB_APP_CLIENT_SECRET", "")
GITHUB_APP_PRIVATE_KEY_B64 = os.environ.get("GITHUB_APP_PRIVATE_KEY_B64", "")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# LLM Provider

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

# Monitoring

METRICS_ENABLED = os.environ.get("METRICS_ENABLED", "False").lower() in ("true", "1")

# Sentry — optional error tracking
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
_HAS_SENTRY = False
try:
    import sentry_sdk  # noqa: F401
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    _HAS_SENTRY = True
except ImportError:
    pass

if SENTRY_DSN and _HAS_SENTRY:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        environment="production" if not DEBUG else "development",
    )

# Logging

# Log level from env, falling back to DEBUG-conditional default
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")

# Detect if JSON logging should be used (default: auto-detect by presence of JSON_FORMAT env var)
USE_JSON_LOGGING = os.environ.get("JSON_LOG", "0").lower() in ("true", "1", "yes")

if USE_JSON_LOGGING:
    _log_format_class = "sentinel_review.logging_filters.JSONFormatter"
    _log_format_config = {}
else:
    _log_format_class = "logging.Formatter"
    _log_format_config = {
        "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
        "style": "{",
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact": {
            "()": "sentinel_review.logging_filters.RedactingFilter",
        },
        "mapping_args": {
            "()": "sentinel_review.logging_filters.MappingArgsFilter",
        },
    },
    "formatters": {
        "standard": {
            "()": _log_format_class,
            **_log_format_config,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["mapping_args", "redact"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "sentinel_review": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
