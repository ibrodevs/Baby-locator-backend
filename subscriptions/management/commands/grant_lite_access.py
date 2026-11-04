from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from accounts.models import User
from subscriptions.models import LiteAccessGrant


class Command(BaseCommand):
    help = "Issue/revoke an explicit server-owned family Lite license; never a public HTTP capability."

    def add_arguments(self, parser):
        parser.add_argument("--parent-id", type=int, required=True)
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--revoke", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["days"] <= 366:
            raise CommandError("days must be between 1 and 366")
        owner = User.objects.filter(pk=options["parent_id"], role="parent").first()
        if not owner:
            raise CommandError("Parent account not found")
        LiteAccessGrant.objects.update_or_create(owner=owner, defaults={"expires_at": timezone.now() + timedelta(days=options["days"]), "revoked_at": timezone.now() if options["revoke"] else None, "source": "admin"})
        self.stdout.write("Family Lite license updated.")
