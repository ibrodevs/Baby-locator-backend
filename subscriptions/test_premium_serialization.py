import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserSerializer
from subscriptions.models import CustomerEntitlement, LiteAccessGrant
from subscriptions.services import sync_subscriber


class PremiumSerializationTests(TestCase):

    def setUp(self):
        self.parent = User.objects.create_user(
            username="premium_serializer_parent",
            password="temporary-test-password",
            role=User.ROLE_PARENT,
        )
        self.child = User.objects.create_user(
            username="premium_serializer_child",
            password="temporary-test-password",
            role=User.ROLE_CHILD,
            parent=self.parent,
        )
        self.expiry = timezone.now() + timedelta(days=30)

    def create_grant(self, **extra):
        values = {
            "owner": self.parent,
            "expires_at": self.expiry,
            "source": "admin_premium",
        }
        values.update(extra)
        return LiteAccessGrant.objects.create(**values)

    def test_no_premium_access(self):
        data = UserSerializer(self.parent).data

        self.assertFalse(data["is_premium"])
        self.assertEqual(data["premium_access_source"], "none")
        self.assertIsNone(data["premium_expires_at"])

    def test_administrative_access(self):
        self.create_grant()

        data = UserSerializer(self.parent).data

        self.assertTrue(data["is_premium"])
        self.assertEqual(
            data["premium_access_source"],
            "administrative",
        )
        self.assertEqual(
            data["premium_expires_at"],
            serializers.DateTimeField().to_representation(self.expiry),
        )
        self.assertEqual(data["premium_product_id"], "")

    def test_child_inherits_administrative_access(self):
        self.create_grant()

        data = UserSerializer(self.child).data

        self.assertTrue(data["is_premium"])
        self.assertEqual(
            data["premium_access_source"],
            "administrative",
        )
        self.assertEqual(
            data["premium_expires_at"],
            serializers.DateTimeField().to_representation(self.expiry),
        )

    def test_expired_grant_does_not_give_access(self):
        self.create_grant(
            expires_at=timezone.now() - timedelta(days=1)
        )

        data = UserSerializer(self.parent).data

        self.assertFalse(data["is_premium"])
        self.assertEqual(data["premium_access_source"], "none")

    def test_revoked_grant_does_not_give_access(self):
        self.create_grant(revoked_at=timezone.now())

        data = UserSerializer(self.parent).data

        self.assertFalse(data["is_premium"])
        self.assertEqual(data["premium_access_source"], "none")

    def test_existing_local_premium(self):
        self.parent.is_premium = True
        self.parent.premium_product_id = "yearly"
        self.parent.premium_expires_at = self.expiry
        self.parent.save()

        data = UserSerializer(self.parent).data

        self.assertTrue(data["is_premium"])
        self.assertEqual(
            data["premium_access_source"],
            "local_premium",
        )
        self.assertEqual(data["premium_product_id"], "yearly")

    @override_settings(
        REVENUECAT_SECRET_API_KEY="test-only-mocked-secret"
    )
    def test_admin_access_survives_empty_revenuecat_sync(self):
        self.create_grant()

        self.parent.is_premium = True
        self.parent.premium_product_id = "yearly"
        self.parent.premium_expires_at = self.expiry
        self.parent.save()

        CustomerEntitlement.objects.create(
            user=self.parent,
            product_id="yearly",
            expires_at=self.expiry,
            lifetime=False,
            revoked=False,
            updated_at=timezone.now(),
        )

        response = json.dumps({
            "subscriber": {
                "entitlements": {},
                "subscriptions": {},
                "non_subscriptions": {},
            }
        }).encode()

        with patch(
            "subscriptions.services.urlopen",
            return_value=BytesIO(response),
        ) as mocked:
            sync_subscriber(self.parent)
            mocked.assert_called_once()

        self.parent.refresh_from_db()
        data = UserSerializer(self.parent).data

        self.assertFalse(self.parent.is_premium)
        self.assertTrue(data["is_premium"])
        self.assertEqual(
            data["premium_access_source"],
            "administrative",
        )
        self.assertEqual(
            data["premium_expires_at"],
            serializers.DateTimeField().to_representation(self.expiry),
        )
        self.assertTrue(
            CustomerEntitlement.objects.get(
                user=self.parent,
                product_id="yearly",
            ).revoked
        )
