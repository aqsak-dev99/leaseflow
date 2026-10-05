from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.accounts",
    "apps.properties",
    "apps.documents",
    "apps.maintenance",
    "apps.billing",
    "apps.agents",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.OrganizationMiddleware",
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

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REDIS_URL = env("REDIS_URL")
if REDIS_URL.startswith("rediss://") and "ssl_cert_reqs" not in REDIS_URL:
    REDIS_URL += "?ssl_cert_reqs=required"
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

GROQ_API_KEY = env("GROQ_API_KEY", default="")
GOOGLE_API_KEY = env("GOOGLE_API_KEY", default="")
LLM_MODEL = env("LLM_MODEL", default="openai/gpt-oss-120b")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="models/gemini-embedding-001")

FAKE_GATEWAY_WEBHOOK_SECRET = env("FAKE_GATEWAY_WEBHOOK_SECRET", default="dev-only-webhook-secret")

CELERY_BEAT_SCHEDULE = {
    "generate-monthly-invoices": {
        "task": "apps.billing.tasks.generate_monthly_invoices",
        "schedule": crontab(day_of_month="1", hour="6", minute="0"),
    },
    "mark-overdue-invoices": {
        "task": "apps.billing.tasks.mark_overdue_invoices",
        "schedule": crontab(hour="7", minute="0"),
    },
}
