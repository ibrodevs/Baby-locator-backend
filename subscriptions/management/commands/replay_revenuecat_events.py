from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from subscriptions.models import RevenueCatWebhookEvent
from subscriptions.services import process_revenuecat_event, SubscriptionSyncError


class Command(BaseCommand):
    help = 'Retry pending webhook events without requiring another RevenueCat delivery.'
    def handle(self, *args, **options):
        expired=timezone.now()-timedelta(days=30)
        RevenueCatWebhookEvent.objects.filter(status='pending',processed_at__lt=expired).update(status='ignored',error='unmatched_event_expired',raw_payload={},app_user_id='')
        count=0
        for event in RevenueCatWebhookEvent.objects.filter(status='pending').order_by('processed_at')[:100]:
            try:
                process_revenuecat_event(event.raw_payload)
                count+=1
            except (SubscriptionSyncError,ValueError):
                pass
        self.stdout.write(f'Processed pending webhook events: {count}')
