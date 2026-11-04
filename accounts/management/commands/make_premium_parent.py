import os
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from accounts.models import User
from subscriptions.models import LiteAccessGrant


class Command(BaseCommand):
    help = "Explicit administrative family grant; never logs or resets an existing password implicitly."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password", default=None, help="Prefer BABY_LOCATOR_BOOTSTRAP_PASSWORD instead of process arguments.")
        parser.add_argument("--display-name", default="Premium Parent")
        parser.add_argument("--days", type=int, default=365)

    def handle(self, *args, **options):
        if not 1 <= options['days'] <= 3660:
            raise CommandError('days must be between 1 and 3660')
        user = User.objects.filter(username=options['username'].strip()).first()
        password = options['password'] or os.getenv('BABY_LOCATOR_BOOTSTRAP_PASSWORD')
        if user is None:
            if not password:
                raise CommandError('Set BABY_LOCATOR_BOOTSTRAP_PASSWORD securely before creating an account.')
            user = User.objects.create_user(username=options['username'].strip(), password=password, role='parent', display_name=options['display_name'])
        elif user.role != 'parent':
            raise CommandError('The existing account is not a parent; no role/password was changed.')
        expiry = timezone.now()+timedelta(days=options['days'])
        LiteAccessGrant.objects.update_or_create(owner=user, defaults={'expires_at':expiry,'revoked_at':None,'source':'admin_premium'})
        self.stdout.write('Administrative family access granted. No password was printed or reset.')
