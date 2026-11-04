"""Validate production configuration without ever printing credentials."""
import json
import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = 'Check required production settings, Firebase credential metadata and DB/Redis connectivity.'
    def add_arguments(self, parser):
        parser.add_argument('--skip-connectivity', action='store_true')
    def handle(self, *args, **options):
        errors=[]
        def require(ok, message):
            if not ok: errors.append(message)
        require(not settings.DEBUG, 'DJANGO_DEBUG must be False')
        require(not settings.IS_TEST, 'IS_TEST must be False')
        require(len(settings.SECRET_KEY)>=50, 'DJANGO_SECRET_KEY must be unique and at least 50 characters')
        require(settings.ALLOWED_HOSTS and '*' not in settings.ALLOWED_HOSTS, 'Set explicit DJANGO_ALLOWED_HOSTS')
        require(settings.REVENUECAT_PUBLIC_API_KEY_ANDROID.startswith('goog_'), 'Set Android REVENUECAT_PUBLIC_API_KEY_ANDROID from the matching RevenueCat app')
        require(settings.REVENUECAT_SECRET_API_KEY.startswith('sk_'), 'Set REVENUECAT_SECRET_API_KEY (server-only secret key, sk_ prefix)')
        require(len(settings.REVENUECAT_WEBHOOK_AUTH_HEADER)>=32, 'Set matching long REVENUECAT_WEBHOOK_AUTH_HEADER in server and Dashboard')
        require(bool(settings.REVENUECAT_APP_IDS), 'Set REVENUECAT_APP_IDS to RevenueCat Android app id(s)')
        require(bool(settings.WEBRTC_TURN_URLS) and (bool(settings.WEBRTC_TURN_SECRET) or bool(settings.WEBRTC_TURN_USERNAME and settings.WEBRTC_TURN_CREDENTIAL)), 'Configure WEBRTC_TURN_URLS and TURN credentials')
        require(bool(settings.REDIS_URL), 'Set REDIS_URL for shared production throttling/cache')
        path=Path(settings.FIREBASE_SERVICE_ACCOUNT_KEY)
        try:
            credential=json.loads(path.read_text())
            require(credential.get('type')=='service_account' and bool(credential.get('private_key')), 'Firebase credential is not a service account JSON')
            expected=settings.FIREBASE_EXPECTED_PROJECT_ID
            require(bool(expected) and credential.get('project_id')==expected, 'Set FIREBASE_EXPECTED_PROJECT_ID matching Android Firebase config')
            require(os.name!='posix' or path.stat().st_mode & 0o077 == 0, 'Restrict Firebase credential permissions to owner (chmod 600)')
        except (OSError,ValueError):
            errors.append('FIREBASE_SERVICE_ACCOUNT_KEY must point to a readable private service account JSON')
        if not options['skip_connectivity']:
            try:
                with connection.cursor() as cursor: cursor.execute('SELECT 1')
            except Exception: errors.append('Database connectivity failed')
            if settings.REDIS_URL:
                try:
                    import redis
                    redis.Redis.from_url(settings.REDIS_URL,socket_connect_timeout=3,socket_timeout=3).ping()
                except Exception: errors.append('Redis connectivity failed')
        if errors:
            raise CommandError('\n'.join(errors))
        self.stdout.write('Production configuration checks passed. This does not verify Play products, webhook delivery or TURN media connectivity.')
