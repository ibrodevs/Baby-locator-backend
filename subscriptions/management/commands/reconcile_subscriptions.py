from django.core.management.base import BaseCommand, CommandError
from accounts.models import User
from subscriptions.services import sync_subscriber, SubscriptionSyncError


class Command(BaseCommand):
    help = "Resync subscription owners with RevenueCat (read-only provider API). Schedule periodically."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int)

    def handle(self, *args, **options):
        query = User.objects.filter(role="parent")
        if options["user_id"]:
            query = query.filter(pk=options["user_id"])
        failed = 0
        for user in query.iterator():
            try:
                sync_subscriber(user)
            except SubscriptionSyncError:
                failed += 1
        if failed:
            raise CommandError(f"Subscription sync failed for {failed} accounts; check provider configuration/connectivity.")
        self.stdout.write("Subscription reconciliation completed.")
