"""Run a management command with the same protected env file as systemd."""
import os
import sys
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values('/etc/baby-locator/backend.env')
if not values or any(value is None for value in values.values()):
    raise SystemExit('Missing or invalid /etc/baby-locator/backend.env')
os.environ.update(values)
os.chdir(root)
os.execv(sys.executable, [sys.executable, str(root / 'manage.py'), *sys.argv[1:]])
