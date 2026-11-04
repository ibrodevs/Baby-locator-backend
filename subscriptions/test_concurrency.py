from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import skipUnless
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from accounts.models import User
from .models import RevenueCatWebhookEvent, CustomerEntitlement
from .services import process_revenuecat_event, has_premium_access


@skipUnless(connection.vendor == 'postgresql', 'Row-lock concurrency requires PostgreSQL')
@override_settings(REVENUECAT_APP_IDS=['app_test'], REVENUECAT_ALLOWED_ENVIRONMENTS=['PRODUCTION'])
class WebhookConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user=User.objects.create_user(username='concurrent',role='parent')
        now=timezone.now()
        self.payload={'event':{'id':'parallel','type':'RENEWAL','app_id':'app_test','environment':'PRODUCTION','app_user_id':str(self.user.pk),'product_id':'monthly','entitlement_ids':['family_security_pro'],'event_timestamp_ms':int(now.timestamp()*1000),'expiration_at_ms':int((now+timedelta(days=1)).timestamp()*1000)}}

    def test_same_event_in_parallel_is_processed_once(self):
        def deliver(_):
            try: return process_revenuecat_event(self.payload)['status']
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(deliver,range(4)))
        self.assertEqual(statuses.count('processed'),1)
        self.assertEqual(RevenueCatWebhookEvent.objects.count(),1)
        self.assertEqual(CustomerEntitlement.objects.count(),1)
        self.user.refresh_from_db(); self.assertTrue(has_premium_access(self.user))
