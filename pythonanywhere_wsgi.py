import os
import sys


PROJECT_HOME = "/home/backend21/baby_locator/backend"

if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# PythonAnywhere web app does not use your shell ~/.bashrc exports,
# so keep production env vars here or in the virtualenv postactivate script.
os.environ.setdefault(
    "DJANGO_SECRET_KEY",
    "replace-with-a-long-random-secret-key-before-launch",
)
os.environ.setdefault("DJANGO_DEBUG", "False")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "*")
os.environ.setdefault("DJANGO_CORS_ALLOW_ALL_ORIGINS", "True")
os.environ.setdefault(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "https://backend21.pythonanywhere.com",
)
os.environ.setdefault("DJANGO_SECURE_SSL_REDIRECT", "True")
os.environ.setdefault("DJANGO_SECURE_HSTS_SECONDS", "31536000")
os.environ.setdefault("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "True")
os.environ.setdefault("DJANGO_SECURE_HSTS_PRELOAD", "True")

from django.core.wsgi import get_wsgi_application


application = get_wsgi_application()
