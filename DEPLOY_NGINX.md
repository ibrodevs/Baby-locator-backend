# Production deployment

Use deploy/nginx.conf.example, deploy/baby-locator.service and gunicorn.conf.py as reviewed templates.
Replace placeholders, configure HTTPS and private environment files before installing them.

The main audio UI uses WebRTC; its media does not pass through Gunicorn. TURN is configured separately.
Legacy HTTP PCM endpoints now use Redis streams across workers. Set LIVE_AUDIO_REDIS_URL (or REDIS_URL).
Without a configured shared broker, production HTTP PCM returns 503 instead of silently routing audio
into different worker memories. Do not expose Redis to the public internet.

All audio capture requires an active, child-confirmed MonitorSession. A background push only invites
the child to open the app. Keep /media/ routed to authenticated Django; never add a public media alias.
Query strings carry private session metadata; omit them from access logs.

Commands for a reviewed rollout (not automatically executed):

1. Back up PostgreSQL and private media; verify restore and record deployed source SHA.
2. Create a fresh Python 3.12 venv; install requirements.txt with --require-hashes.
3. Install protected server ENV and Firebase service-account file; chmod 600.
4. Run manage.py check, manage.py check --deploy and manage.py production_check.
5. Run manage.py migrate --plan, then reviewed migrations, then collectstatic.
6. Validate nginx/systemd configuration, deploy backend and the matching paid mobile build together.
7. Schedule reconcile_subscriptions, process_account_deletions and cleanup_media (dry-run before --apply).
8. Verify Play test purchase/restore, webhook, FCM, child consent, TURN relay and stop on real devices.

Migrations close old audio sessions and invalidate queued commands before the upgrade. Location capture
times are backfilled from existing created_at. AppIcon keeps its existing AutoField primary key.

Old clients cannot provide the new per-session consent. Upgrade the paid child app for audio. Lite source
is deliberately unchanged; server-side Lite licenses are explicit admin grants, never header-based.
Do not rewrite Git history, rotate live keys, restart production or submit a Play release automatically.
