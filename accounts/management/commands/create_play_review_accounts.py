import os
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from accounts.models import InviteCode, User

class Command(BaseCommand):
    help = "Idempotently create or update Google Play reviewer parent and child accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--parent-username",
            type=str,
            default=os.getenv("PLAY_REVIEW_PARENT_USERNAME", "play_reviewer_parent"),
            help="Parent reviewer username",
        )
        parser.add_argument(
            "--parent-password",
            type=str,
            default=os.getenv("PLAY_REVIEW_PARENT_PASSWORD", ""),
            help="Parent reviewer password",
        )
        parser.add_argument(
            "--child-username",
            type=str,
            default=os.getenv("PLAY_REVIEW_CHILD_USERNAME", "play_reviewer_child"),
            help="Child reviewer username",
        )
        parser.add_argument(
            "--child-password",
            type=str,
            default=os.getenv("PLAY_REVIEW_CHILD_PASSWORD", ""),
            help="Child reviewer password",
        )

    def handle(self, *args, **options):
        p_username = options["parent_username"].strip()
        p_password = options["parent_password"]
        c_username = options["child_username"].strip()
        c_password = options["child_password"]

        if not p_password or not c_password:
            raise CommandError("Set unique PLAY_REVIEW_PARENT_PASSWORD and PLAY_REVIEW_CHILD_PASSWORD securely.")

        # 1. Parent Account
        parent, p_created = User.objects.get_or_create(
            username=p_username,
            defaults={
                "role": User.ROLE_PARENT,
                "display_name": "Reviewer Parent",
                "is_premium": True,
                "premium_entitlement": "family_security_pro",
                "premium_product_id": "yearly",
                "premium_expires_at": timezone.now() + timedelta(days=3650),
            },
        )
        parent.role = User.ROLE_PARENT
        parent.is_premium = True
        parent.premium_expires_at = timezone.now() + timedelta(days=3650)
        parent.set_password(p_password)
        parent.save()

        # 2. Child Account
        child, c_created = User.objects.get_or_create(
            username=c_username,
            defaults={
                "role": User.ROLE_CHILD,
                "display_name": "Reviewer Child",
            },
        )
        child.role = User.ROLE_CHILD
        child.set_password(c_password)
        child.save()

        # 3. Ensure linking
        child.parent = parent
        child.save()

        # 4. Generate or refresh invite code
        invite = InviteCode.objects.filter(parent=parent, used_by__isnull=True).first()
        if not invite:
            invite = InviteCode.objects.create(code=InviteCode.generate_code(), parent=parent, expires_at=timezone.now() + timedelta(days=30))

        self.stdout.write(self.style.SUCCESS("Google Play reviewer accounts ready:"))
        self.stdout.write(f"  Parent Username: {p_username}")
        self.stdout.write("  Parent password: configured (not printed)")
        self.stdout.write(f"  Child Username:  {c_username}")
        self.stdout.write("  Child password: configured (not printed)")
        self.stdout.write(f"  Active Invite Code: {invite.code if invite else 'N/A'}")
        self.stdout.write(f"  Linked Status:   {'Newly Created' if (p_created or c_created) else 'Verified Existing'}")
