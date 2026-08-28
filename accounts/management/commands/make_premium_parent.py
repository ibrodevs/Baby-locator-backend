from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from accounts.models import User

class Command(BaseCommand):
    help = "Create or upgrade a parent account to full PRO/Premium status"

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Username or email of the parent account")
        parser.add_argument("--password", type=str, default="FamilyPro2026!", help="Password if creating new user")
        parser.add_argument("--display-name", type=str, default="Premium Parent", help="Display name")

    def handle(self, *args, **options):
        username = options["username"].strip()
        password = options["password"]
        display_name = options["display_name"]

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "role": User.ROLE_PARENT,
                "display_name": display_name,
                "is_premium": True,
                "premium_entitlement": "family_security_pro",
                "premium_product_id": "yearly",
                "premium_expires_at": timezone.now() + timedelta(days=3650),
            }
        )

        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Successfully CREATED Premium Parent account '{username}' with password '{password}'"))
        else:
            user.role = User.ROLE_PARENT
            user.is_premium = True
            user.premium_entitlement = "family_security_pro"
            user.premium_product_id = "yearly"
            user.premium_expires_at = timezone.now() + timedelta(days=3650)
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Successfully UPGRADED account '{username}' to Premium Parent with password '{password}'"))
