from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from accounts.models import ExternalAccountDeletion


class Command(BaseCommand):
    help = "Retry queued RevenueCat customer erasure; does not cancel store subscriptions."

    def handle(self, *args, **options):
        key=settings.REVENUECAT_SECRET_API_KEY
        if not key:
            raise CommandError('Configure REVENUECAT_SECRET_API_KEY before processing provider deletions.')
        ExternalAccountDeletion.objects.filter(completed_at__lt=timezone.now()-timedelta(days=30)).delete()
        failed=0
        for task_id in ExternalAccountDeletion.objects.filter(completed_at__isnull=True).values_list('pk',flat=True)[:100]:
            with transaction.atomic():
                task=ExternalAccountDeletion.objects.select_for_update().get(pk=task_id)
                if task.completed_at:
                    continue
                task.attempts+=1
                try:
                    request=Request('https://api.revenuecat.com/v1/subscribers/'+task.app_user_id, method='DELETE', headers={'Authorization':'Bearer '+key})
                    with urlopen(request,timeout=8): pass
                    task.completed_at=timezone.now();task.error_code=''
                except HTTPError as error:
                    if error.code==404: task.completed_at=timezone.now();task.error_code=''
                    else: task.error_code=f'provider_http_{error.code}';failed+=1
                except Exception:
                    task.error_code='provider_unavailable';failed+=1
                task.save(update_fields=['attempts','completed_at','error_code'])
        if failed: raise CommandError(f'{failed} provider deletion requests require retry. No credentials were logged.')
        self.stdout.write('Provider deletion queue processed.')
