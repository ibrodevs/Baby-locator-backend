# Kid Security — Django REST backend

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations accounts tracking
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver 0.0.0.0:8000
```

Environment variables:

- `DJANGO_SECRET_KEY` - secret key for production
- `DJANGO_DEBUG` - `True` or `False`
- `DJANGO_ALLOWED_HOSTS` - comma-separated hosts, default `*`
- `DJANGO_CORS_ALLOW_ALL_ORIGINS` - `True` or `False`
- `DJANGO_CSRF_TRUSTED_ORIGINS` - comma-separated URLs, for example `https://yourusername.pythonanywhere.com`
- `DJANGO_SECURE_SSL_REDIRECT` - redirect HTTP to HTTPS in production
- `DJANGO_SECURE_HSTS_SECONDS` - HSTS duration in seconds
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` - include subdomains in HSTS policy
- `DJANGO_SECURE_HSTS_PRELOAD` - enable HSTS preload flag

Example file for PythonAnywhere: [`.env.pythonanywhere.example`](/Users/imac5/Desktop/baby_locator/backend/.env.pythonanywhere.example)

## Deploy to PythonAnywhere

### 1. Upload the project

You can upload it in any convenient way:

- `git clone` the repository in a PythonAnywhere Bash console
- upload a zip archive through the **Files** tab and unpack it
- use `scp`/SFTP if you keep the project outside Git

Expected project path in examples below:

```bash
/home/yourusername/baby_locator/backend
```

### 2. Create virtualenv and install dependencies

```bash
mkvirtualenv --python=/usr/bin/python3.10 baby-locator-backend
workon baby-locator-backend
cd ~/baby_locator/backend
pip install -r requirements.txt
```

### 3. Set environment variables

In PythonAnywhere Bash console:

```bash
export DJANGO_SECRET_KEY="replace-with-a-long-random-secret"
export DJANGO_DEBUG=False
export DJANGO_ALLOWED_HOSTS="*"
export DJANGO_CORS_ALLOW_ALL_ORIGINS=True
export DJANGO_CSRF_TRUSTED_ORIGINS="https://yourusername.pythonanywhere.com"
export DJANGO_SECURE_SSL_REDIRECT=True
export DJANGO_SECURE_HSTS_SECONDS=31536000
export DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
export DJANGO_SECURE_HSTS_PRELOAD=True
```

If you want these variables to persist, add them to `~/.bashrc` and reload the shell.

### 4. Prepare database and static files

```bash
cd ~/baby_locator/backend
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### 5. Configure the Web app

In the **Web** tab on PythonAnywhere:

- create a new web app with **Manual configuration**
- choose Python `3.10`
- set the virtualenv path to `/home/yourusername/.virtualenvs/baby-locator-backend`

Then edit the WSGI file and replace its contents with:

```python
import os
import sys

project_home = "/home/yourusername/baby_locator/backend"
if project_home not in sys.path:
    sys.path.append(project_home)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### 6. Add static and media mappings

In the same **Web** tab:

- URL `/static/` -> Directory `/home/yourusername/baby_locator/backend/staticfiles`
- URL `/media/` -> Directory `/home/yourusername/baby_locator/backend/media`

### 7. Reload the app

Press **Reload** in the **Web** tab.

If something does not start, inspect:

- web app error log
- server log
- output of `python manage.py check --deploy`

## API

All requests use `Authorization: Token <key>` except register/login.

### Auth
- `POST /api/auth/register/` — parent sign-up. Body: `{username, password, display_name?}`. Returns `{token, user}`.
- `POST /api/auth/login/` — sign-in (parent or child). Body: `{username, password}`. Returns `{token, user}`.
- `GET  /api/auth/me/` — current user.

### Children (parent only)
- `GET  /api/auth/children/` — list my children.
- `POST /api/auth/children/` — create child account. Body: `{username, password, display_name?}`.

### Location
- `POST /api/locations/` — child shares location. Body: `{lat, lng, address?, battery?, active?}`.
- `GET  /api/children/<id>/location/` — latest location of a child (parent or that child).
- `GET  /api/children/<id>/history/` — last 100 points.

## Models
- `accounts.User` (custom): `role` ∈ {parent, child}, `parent` FK for children.
- `tracking.LocationUpdate`: child, lat, lng, address, battery, active, created_at.
