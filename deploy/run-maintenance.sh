#!/bin/sh
# Run as the service user from systemd; env is supplied by EnvironmentFile.
set -eu
cd /srv/baby-locator/backend
result=0
/srv/baby-locator/venv/bin/python manage.py replay_revenuecat_events || result=1
/srv/baby-locator/venv/bin/python manage.py process_account_deletions || result=1
/srv/baby-locator/venv/bin/python manage.py cleanup_media --apply || result=1
exit "$result"
