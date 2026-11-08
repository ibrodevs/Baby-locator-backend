from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Production ENV wins; never search a parent directory for credentials.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

import os



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

DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "dev-secret-change-me":
    raise ImproperlyConfigured("Set a unique DJANGO_SECRET_KEY in the server environment.")
IS_TEST = env_bool("IS_TEST", False)
GOOGLE_MAPS_API_KEY = (
    os.getenv("GOOGLE_MAPS_ANDROID_API_KEY")
    or os.getenv("GOOGLE_MAPS_API_KEY")
    or os.getenv("MAPS_API_KEY")
    or ""
).strip()
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"] if DEBUG else [])
if not DEBUG and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS in production.")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

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
        "PASSWORD": os.getenv("DJANGO_DB_PASSWORD", ""),
        "HOST": os.getenv("DJANGO_DB_HOST", "localhost"),
        "PORT": os.getenv("DJANGO_DB_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_PARSER_CLASSES": ["accounts.parsers.ObjectJSONParser", "rest_framework.parsers.FormParser", "rest_framework.parsers.MultiPartParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.EditionTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle", "rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "3000/min", "auth": "15/min", "subscription_sync": "12/min", "integrity": "10/min", "geocoding": "60/min"},
}

CORS_ALLOW_ALL_ORIGINS = DEBUG and env_bool("DJANGO_CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOWED_ORIGINS = env_list("DJANGO_CORS_ALLOWED_ORIGINS", [])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (avatars)
MEDIA_URL = "/media/"
media_root_env = os.getenv("DJANGO_MEDIA_ROOT")
if media_root_env and not Path(media_root_env).is_absolute():
    raise ImproperlyConfigured("DJANGO_MEDIA_ROOT must be an absolute path")
MEDIA_ROOT = Path(media_root_env) if media_root_env else BASE_DIR / "media"

USE_X_FORWARDED_HOST = True

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False
    )
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
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
REVENUECAT_PUBLIC_API_KEY_ANDROID = os.getenv(
    "REVENUECAT_PUBLIC_API_KEY_ANDROID",
    os.getenv("REVENUECAT_PUBLIC_API_KEY", ""),
)
REVENUECAT_PUBLIC_API_KEY_IOS = os.getenv("REVENUECAT_PUBLIC_API_KEY_IOS", "")
REVENUECAT_PUBLIC_API_KEY_FALLBACK = os.getenv("REVENUECAT_PUBLIC_API_KEY", "")
REVENUECAT_ENTITLEMENT_ID = os.getenv(
    "REVENUECAT_ENTITLEMENT_ID",
    "family_security_pro",
)
REVENUECAT_PREMIUM_PRODUCT_IDS = env_list(
    "REVENUECAT_PREMIUM_PRODUCT_IDS",
    [
        "monthly",
        "yearly",
        "lifetime",
        "com.location.tracke.parental.control.monthly",
        "com.location.tracke.parental.control.yearly",
    ],
)
REVENUECAT_LIFETIME_PRODUCT_IDS = env_list(
    "REVENUECAT_LIFETIME_PRODUCT_IDS",
    [],
)
# RevenueCat webhooks support a configured Authorization header. Store the
# full expected header value here, for example:
#   Bearer super-secret-revenuecat-webhook-token
REVENUECAT_WEBHOOK_AUTH_HEADER = os.getenv(
    "REVENUECAT_WEBHOOK_AUTH_HEADER",
    "",
)

# Server-only credentials. Never expose these through the public config endpoint.
REVENUECAT_SECRET_API_KEY = os.getenv("REVENUECAT_SECRET_API_KEY", "")
REVENUECAT_APP_IDS = env_list("REVENUECAT_APP_IDS", [])
REVENUECAT_ALLOWED_ENVIRONMENTS = env_list("REVENUECAT_ALLOWED_ENVIRONMENTS", ["PRODUCTION"])
REVENUECAT_HTTP_TIMEOUT_SECONDS = 8
MONITOR_REQUEST_TTL_SECONDS = 120
MONITOR_SESSION_MAX_SECONDS = 600
MONITOR_HEARTBEAT_TIMEOUT_SECONDS = 45
COMMAND_LEASE_SECONDS = 20
COMMAND_TTL_SECONDS = 120
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_MAX_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Shared cache required for rate limiting when more than one worker runs.
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
LIVE_AUDIO_REDIS_URL = os.getenv("LIVE_AUDIO_REDIS_URL", REDIS_URL)

GOOGLE_GEOCODING_API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY", "")
FIREBASE_EXPECTED_PROJECT_ID = os.getenv("FIREBASE_EXPECTED_PROJECT_ID", "")
