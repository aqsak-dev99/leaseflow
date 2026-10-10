"""Production settings. Everything secret comes from environment variables."""

from .base import *  # noqa: F403
from .base import BASE_DIR, MIDDLEWARE, env

DEBUG = False

# Render tells the service its own public address; extra hosts can be added by hand.
RENDER_HOST = env("RENDER_EXTERNAL_HOSTNAME", default="")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[]) + ([RENDER_HOST] if RENDER_HOST else [])
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]
SITE_URL = env("SITE_URL", default=f"https://{RENDER_HOST}" if RENDER_HOST else "")

# HTTPS only. The host's proxy ends the secure connection and tells us so in this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Static files: collected once at build time, compressed, and given a name that
# changes when the file changes, so browsers never show an old stylesheet.
STATIC_ROOT = BASE_DIR / "staticfiles"
MIDDLEWARE = [MIDDLEWARE[0], "whitenoise.middleware.WhiteNoiseMiddleware", *MIDDLEWARE[1:]]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Keep database connections open between requests, and check them before reuse.
DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# No email service is connected yet, so emails are dropped instead of failing.
# Invitation links are still shown to the landlord to copy.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.dummy.EmailBackend")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
