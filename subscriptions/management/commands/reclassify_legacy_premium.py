from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from accounts.models import User
from subscriptions.models import CustomerEntitlement, LiteAccessGrant
from subscriptions.services import has_premium_access


class Command(BaseCommand):
    help = "Review or explicitly convert an old local Premium grant."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--expected-db", required=True)
        parser.add_argument(
            "--source",
            required=True,
            choices=["legacy_manual", "legacy_test"],
        )
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--verified-no-purchases",
            action="store_true",
        )

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database = cursor.fetchone()[0]

        if database != options["expected_db"]:
            raise CommandError("Database mismatch. No changes made.")

        if options["user_id"] <= 0:
            raise CommandError("Invalid user ID.")

        if options["apply"] and not options["verified_no_purchases"]:
            raise CommandError(
                "Explicit confirmation of absent RevenueCat "
                "purchases is required."
            )

        with transaction.atomic():
            try:
                user = User.objects.select_for_update().get(
                    pk=options["user_id"]
                )
            except User.DoesNotExist:
                raise CommandError("User not found.") from None

            if LiteAccessGrant.objects.filter(owner=user).exists():
                raise CommandError(
                    "Administrative grant already exists. "
                    "Manual review required."
                )

            rows = list(
                CustomerEntitlement.objects
                .select_for_update()
                .filter(user=user)
            )

            if (
                user.role != User.ROLE_PARENT
                or not user.is_premium
                or user.premium_synced_at is not None
                or user.premium_product_id != "yearly"
                or user.premium_expires_at is None
                or user.premium_expires_at <= timezone.now()
                or len(rows) != 1
                or rows[0].product_id != "yearly"
                or rows[0].revoked
                or rows[0].lifetime
                or rows[0].expires_at != user.premium_expires_at
            ):
                raise CommandError(
                    "Legacy grant does not match the expected "
                    "pattern. Manual review required."
                )

            self.stdout.write(f"DATABASE: {database}")
            self.stdout.write(f"USER ID: {user.pk}")
            self.stdout.write(f"GRANT SOURCE: {options['source']}")
            self.stdout.write(
                f"ORIGINAL EXPIRY: {user.premium_expires_at}"
            )

            if not options["apply"]:
                self.stdout.write(
                    "DRY RUN: ELIGIBLE FOR REVIEW"
                )
                self.stdout.write("DATABASE: UNCHANGED")
                return

            expiry = user.premium_expires_at

            LiteAccessGrant.objects.create(
                owner=user,
                expires_at=expiry,
                source=options["source"],
            )

            rows[0].revoked = True
            rows[0].save(update_fields=["revoked"])

            user.is_premium = False
            user.premium_entitlement = ""
            user.premium_product_id = ""
            user.premium_expires_at = None
            user.premium_updated_at = timezone.now()

            user.save(update_fields=[
                "is_premium",
                "premium_entitlement",
                "premium_product_id",
                "premium_expires_at",
                "premium_updated_at",
            ])

            if not has_premium_access(user):
                raise CommandError(
                    "Access check failed. Transaction rolled back."
                )

            self.stdout.write(
                self.style.SUCCESS(
                    "CONVERTED: administrative access active"
                )
            )
