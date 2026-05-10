from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path



def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["*"] if DEBUG else [])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "accounts",
    "subscriptions",
    "tracking",
    "chat",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DJANGO_DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DJANGO_DB_NAME", "babydb"),
        "USER": os.getenv("DJANGO_DB_USER", "babyuser"),
        "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", "StrongPassword123"),
        "HOST": os.getenv("DJANGO_DB_HOST", "localhost"),
        "PORT": os.getenv("DJANGO_DB_PORT", "5432"),
    }
}

print("DB PASSWORD:", os.getenv("DJANGO_DB_PASSWORD"))

AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

CORS_ALLOW_ALL_ORIGINS = env_bool("DJANGO_CORS_ALLOW_ALL_ORIGINS", DEBUG)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (avatars)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

USE_X_FORWARDED_HOST = True

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True
    )
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", True)
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Firebase Cloud Messaging
# Path to the service account JSON file downloaded from Firebase Console.
FIREBASE_SERVICE_ACCOUNT_KEY = os.getenv(
    "FIREBASE_SERVICE_ACCOUNT_KEY",
    str(BASE_DIR / "firebase-service-account.json"),
)

# WebRTC ICE servers handed to parent + child clients via the
# /api/webrtc/ice-servers/ endpoint. STUN only by default (works on Wi-Fi,
# fails on most cellular NATs). Set the TURN_* envs to enable a TURN relay so
# parents can hear ambient audio over mobile data when the child phone is
# behind a symmetric NAT.
#
# Two TURN auth modes are supported:
#   1) Static creds — set WEBRTC_TURN_USERNAME + WEBRTC_TURN_CREDENTIAL.
#   2) coturn shared-secret (use-auth-secret) — set WEBRTC_TURN_SECRET. Each
#      client request gets a fresh HMAC-signed time-limited credential, so
#      no long-lived TURN password is ever shipped to the device.
WEBRTC_STUN_URLS = env_list("WEBRTC_STUN_URLS", [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
])
WEBRTC_TURN_URLS = env_list("WEBRTC_TURN_URLS", [])
WEBRTC_TURN_USERNAME = os.getenv("WEBRTC_TURN_USERNAME", "")
WEBRTC_TURN_CREDENTIAL = os.getenv("WEBRTC_TURN_CREDENTIAL", "")
WEBRTC_TURN_SECRET = os.getenv("WEBRTC_TURN_SECRET", "")
WEBRTC_TURN_TTL_SECONDS = int(os.getenv("WEBRTC_TURN_TTL_SECONDS", "86400"))

# RevenueCat
REVENUECAT_ENTITLEMENT_ID = os.getenv(
    "REVENUECAT_ENTITLEMENT_ID",
    "family_security_pro",
)
REVENUECAT_PREMIUM_PRODUCT_IDS = env_list(
    "REVENUECAT_PREMIUM_PRODUCT_IDS",
    ["monthly", "yearly", "lifetime"],
)
REVENUECAT_LIFETIME_PRODUCT_IDS = env_list(
    "REVENUECAT_LIFETIME_PRODUCT_IDS",
    ["lifetime"],
)
# RevenueCat webhooks support a configured Authorization header. Store the
# full expected header value here, for example:
#   Bearer super-secret-revenuecat-webhook-token
REVENUECAT_WEBHOOK_AUTH_HEADER = os.getenv(
    "REVENUECAT_WEBHOOK_AUTH_HEADER",
    "",
)
