import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from accounts.authentication import build_lite_token
from accounts.models import User
from .models import CustomerEntitlement, LiteAccessGrant, RevenueCatWebhookEvent
from .services import has_premium_access, process_revenuecat_event, sync_subscriber, webhook_auth_is_valid, SubscriptionSyncError


@override_settings(REVENUECAT_APP_IDS=["app_test"], REVENUECAT_ALLOWED_ENVIRONMENTS=["PRODUCTION"], REVENUECAT_WEBHOOK_AUTH_HEADER="Bearer test-secret", REVENUECAT_LIFETIME_PRODUCT_IDS=["lifetime"])
class SubscriptionSecurityTests(APITestCase):
    def setUp(self):
        self.parent = User.objects.create_user(username="parent", password="testpass-123", role="parent")
        self.child = User.objects.create_user(username="child", password="testpass-123", role="child", parent=self.parent)
        self.token = Token.objects.create(user=self.parent)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def event(self, kind="RENEWAL", *, event_id="evt1", offset=0, product="monthly", environment="PRODUCTION", **extra):
        now = timezone.now()
        return {"event": {"id": event_id, "type": kind, "app_id": "app_test", "environment": environment,
                "app_user_id": str(self.parent.pk), "product_id": product,
                "entitlement_ids": ["family_security_pro"],
                "event_timestamp_ms": int((now + timedelta(seconds=offset)).timestamp()*1000),
                "expiration_at_ms": int((now + timedelta(days=30)).timestamp()*1000), **extra}}

    def test_header_does_not_grant_lite(self):
        self.assertEqual(self.client.post('/api/revenuecat/lite-token/', {}, HTTP_X_APP_EDITION='lite').status_code, 403)
        self.parent.refresh_from_db()
        self.assertFalse(has_premium_access(self.parent))

    def test_legacy_signed_lite_does_not_grant_access(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token '+build_lite_token(self.token.key))
        self.assertEqual(self.client.get('/api/children/%s/history/' % self.child.pk).status_code,403)

    def test_server_license_and_revocation(self):
        grant = LiteAccessGrant.objects.create(owner=self.parent, expires_at=timezone.now()+timedelta(days=1))
        self.assertTrue(has_premium_access(self.parent))
        self.assertTrue(has_premium_access(self.child))
        grant.revoked_at=timezone.now(); grant.save()
        self.assertFalse(has_premium_access(self.parent))

    def test_expired_boolean_does_not_grant_access(self):
        self.parent.is_premium=True; self.parent.premium_expires_at=timezone.now()-timedelta(seconds=1); self.parent.save()
        self.assertFalse(has_premium_access(self.parent))

    def test_purchase_and_duplicate(self):
        payload=self.event()
        process_revenuecat_event(payload)
        self.assertEqual(process_revenuecat_event(payload)['status'],'duplicate')
        self.parent.refresh_from_db()
        self.assertTrue(has_premium_access(self.parent))
        self.assertEqual(RevenueCatWebhookEvent.objects.count(),1)

    def test_old_expiration_does_not_overwrite_renewal(self):
        process_revenuecat_event(self.event())
        process_revenuecat_event(self.event('EXPIRATION', event_id='old',offset=-60))
        self.parent.refresh_from_db(); self.assertTrue(has_premium_access(self.parent))

    def test_cancel_renewal_keeps_access_until_expiry(self):
        process_revenuecat_event(self.event('CANCELLATION'))
        self.parent.refresh_from_db(); self.assertTrue(has_premium_access(self.parent))

    def test_refund_revokes_lifetime(self):
        process_revenuecat_event(self.event('NON_RENEWING_PURCHASE', product='lifetime',expiration_at_ms=None))
        self.parent.refresh_from_db(); self.assertTrue(has_premium_access(self.parent))
        process_revenuecat_event(self.event('CANCELLATION',event_id='refund',offset=1,product='lifetime',expiration_at_ms=None,cancel_reason='CUSTOMER_SUPPORT'))
        self.parent.refresh_from_db(); self.assertFalse(has_premium_access(self.parent))

    def test_refund_one_product_does_not_revoke_other(self):
        process_revenuecat_event(self.event(product='monthly'))
        process_revenuecat_event(self.event(event_id='year',offset=1,product='yearly'))
        process_revenuecat_event(self.event('EXPIRATION',event_id='expired',offset=2,product='monthly'))
        self.parent.refresh_from_db(); self.assertTrue(has_premium_access(self.parent))

    def test_sandbox_and_wrong_app_are_ignored(self):
        self.assertEqual(process_revenuecat_event(self.event(environment='SANDBOX'))['status'],'ignored')
        self.assertEqual(process_revenuecat_event(self.event(event_id='bad-app',app_id='other'))['status'],'ignored')
        self.parent.refresh_from_db(); self.assertFalse(has_premium_access(self.parent))

    def test_unknown_user_remains_retryable(self):
        payload=self.event(app_user_id='999999')
        with self.assertRaises(SubscriptionSyncError): process_revenuecat_event(payload)
        self.assertEqual(RevenueCatWebhookEvent.objects.get().status,'pending')

    def test_missing_webhook_auth_never_accepted_in_debug(self):
        with override_settings(DEBUG=True,REVENUECAT_WEBHOOK_AUTH_HEADER=''):
            self.assertFalse(webhook_auth_is_valid(None))
        self.assertEqual(self.client.post('/api/revenuecat/webhook/',self.event(),format='json').status_code,401)

    def test_client_cannot_claim_premium(self):
        self.assertEqual(self.client.post('/api/revenuecat/sync/',{'is_premium':True},format='json').status_code,503)
        self.parent.refresh_from_db(); self.assertFalse(self.parent.is_premium)

    @override_settings(REVENUECAT_SECRET_API_KEY='server-only-test-key')
    def test_authoritative_sync_and_expiry(self):
        expiry=(timezone.now()+timedelta(days=30)).isoformat()
        data={'subscriber':{'entitlements':{'family_security_pro':{'product_identifier':'monthly','expires_date':expiry}},'subscriptions':{'monthly':{'is_sandbox':False}}}}
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        with patch('subscriptions.services.urlopen',return_value=Response(json.dumps(data).encode())) as request:
            owner=sync_subscriber(self.parent)
            self.assertTrue(has_premium_access(owner))
            self.assertIn(str(self.parent.pk),request.call_args.args[0].full_url)
        data['subscriber']['entitlements']={}
        with patch('subscriptions.services.urlopen',return_value=Response(json.dumps(data).encode())):
            self.assertFalse(has_premium_access(sync_subscriber(self.parent)))

    @override_settings(REVENUECAT_SECRET_API_KEY='server-only-test-key')
    def test_transfer_resyncs_both_owners(self):
        other=User.objects.create_user(username='other',role='parent')
        payload=self.event('TRANSFER',transferred_from=[str(self.parent.pk)],transferred_to=[str(other.pk)])
        with patch('subscriptions.services.sync_subscriber') as sync:
            process_revenuecat_event(payload)
            self.assertEqual({c.args[0].pk for c in sync.call_args_list},{self.parent.pk,other.pk})

    def test_scheduled_pause_does_not_revoke_current_period(self):
        process_revenuecat_event(self.event('SUBSCRIPTION_PAUSED'))
        self.parent.refresh_from_db(); self.assertTrue(has_premium_access(self.parent))

    def test_dashboard_test_never_grants_or_revokes(self):
        process_revenuecat_event(self.event())
        process_revenuecat_event(self.event('TEST',event_id='dashboard',offset=1))
        self.parent.refresh_from_db(); self.assertTrue(has_premium_access(self.parent))

    def test_cross_product_old_event_is_not_dropped_by_other_product_timestamp(self):
        process_revenuecat_event(self.event(product='monthly',offset=-30))
        process_revenuecat_event(self.event(product='yearly',event_id='year',offset=-10))
        process_revenuecat_event(self.event('EXPIRATION',product='monthly',event_id='monthly-expiry',offset=-20))
        self.assertTrue(CustomerEntitlement.objects.get(user=self.parent,product_id='monthly').revoked)
        self.parent.refresh_from_db();self.assertTrue(has_premium_access(self.parent))

    def test_billing_grace_period_keeps_access(self):
        now = timezone.now()
        process_revenuecat_event(self.event('BILLING_ISSUE', expiration_at_ms=int((now-timedelta(hours=1)).timestamp()*1000), grace_period_expiration_at_ms=int((now+timedelta(days=2)).timestamp()*1000)))
        self.parent.refresh_from_db()
        self.assertTrue(has_premium_access(self.parent))

    def test_test_event_unknown_user_is_ignored(self):
        self.assertEqual(process_revenuecat_event(self.event('TEST', app_user_id='unknown'))['status'], 'ignored')

    def test_pause_without_expiry_preserves_existing_period(self):
        process_revenuecat_event(self.event())
        process_revenuecat_event(self.event('SUBSCRIPTION_PAUSED', event_id='pause-no-expiry', offset=1, expiration_at_ms=None))
        self.parent.refresh_from_db()
        self.assertTrue(has_premium_access(self.parent))

    def test_billing_cancellation_does_not_shorten_known_grace(self):
        now = timezone.now()
        expired = int((now-timedelta(hours=1)).timestamp()*1000)
        grace = int((now+timedelta(days=2)).timestamp()*1000)
        process_revenuecat_event(self.event('BILLING_ISSUE', expiration_at_ms=expired, grace_period_expiration_at_ms=grace))
        process_revenuecat_event(self.event('CANCELLATION', event_id='billing-cancel', offset=1, expiration_at_ms=expired, cancel_reason='BILLING_ERROR'))
        self.parent.refresh_from_db()
        self.assertTrue(has_premium_access(self.parent))


class LegacyPremiumReclassifyCommandTests(APITestCase):
    """Regression tests using Django's separate test database."""

    def setUp(self):
        from django.utils import timezone
        from datetime import timedelta

        self.user = User.objects.create_user(
            username="legacy_command_test_parent",
            password="temporary-test-password",
            role=User.ROLE_PARENT,
        )
        self.expiry = timezone.now() + timedelta(days=3650)

        self.user.is_premium = True
        self.user.premium_product_id = "yearly"
        self.user.premium_entitlement = "family_security_pro"
        self.user.premium_expires_at = self.expiry
        self.user.save()

        CustomerEntitlement.objects.create(
            user=self.user,
            product_id="yearly",
            expires_at=self.expiry,
            lifetime=False,
            revoked=False,
            updated_at=timezone.now(),
        )

    def run_command(self, **extra):
        from django.core.management import call_command
        from django.db import connection
        from io import StringIO

        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database = cursor.fetchone()[0]

        options = {
            "user_id": self.user.pk,
            "source": "legacy_test",
            "expected_db": database,
            "stdout": StringIO(),
        }
        options.update(extra)

        call_command("reclassify_legacy_premium", **options)
        return options["stdout"].getvalue()

    def test_dry_run_does_not_change_data(self):
        output = self.run_command()

        self.assertIn("DRY RUN", output)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_premium)
        self.assertFalse(
            LiteAccessGrant.objects.filter(owner=self.user).exists()
        )
        self.assertFalse(
            CustomerEntitlement.objects.get(user=self.user).revoked
        )

    def test_explicit_conversion_preserves_access(self):
        output = self.run_command(
            apply=True,
            verified_no_purchases=True,
        )

        self.assertIn("CONVERTED", output)

        self.user.refresh_from_db()
        grant = LiteAccessGrant.objects.get(owner=self.user)

        self.assertFalse(self.user.is_premium)
        self.assertEqual(grant.source, "legacy_test")
        self.assertEqual(grant.expires_at, self.expiry)
        self.assertTrue(
            CustomerEntitlement.objects.get(user=self.user).revoked
        )
        self.assertTrue(has_premium_access(self.user))

    def test_wrong_database_is_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command(
                expected_db="wrong_database",
                apply=True,
                verified_no_purchases=True,
            )

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_premium)

    def test_confirmation_is_required(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command(apply=True)

        self.assertFalse(
            LiteAccessGrant.objects.filter(owner=self.user).exists()
        )

    def test_repeated_conversion_is_rejected(self):
        from django.core.management.base import CommandError

        self.run_command(
            apply=True,
            verified_no_purchases=True,
        )

        with self.assertRaises(CommandError):
            self.run_command(
                apply=True,
                verified_no_purchases=True,
            )

        self.assertEqual(
            LiteAccessGrant.objects.filter(owner=self.user).count(),
            1,
        )

    def test_additional_purchase_blocks_conversion(self):
        from django.core.management.base import CommandError

        CustomerEntitlement.objects.create(
            user=self.user,
            product_id="monthly",
            expires_at=self.expiry,
            lifetime=False,
            revoked=False,
            updated_at=timezone.now(),
        )

        with self.assertRaises(CommandError):
            self.run_command(
                apply=True,
                verified_no_purchases=True,
            )

        self.assertFalse(
            LiteAccessGrant.objects.filter(owner=self.user).exists()
        )
