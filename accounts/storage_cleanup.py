"""Delete media after a successful DB commit; failed deletions remain retryable."""
import logging
from django.db import transaction
from django.db.models import FileField
from django.db.models.signals import post_delete, pre_delete, pre_save
from django.dispatch import receiver
from .models import User

logger = logging.getLogger(__name__)


def _remove(storage, name):
    try:
        storage.delete(name)
    except Exception:
        # Do not log the private file name; operator can retry with cleanup_media command.
        logger.error("Private media deletion failed; run cleanup_media --apply.")


@receiver(post_delete)
def remove_files(sender, instance, **kwargs):
    if instance._meta.app_label not in {"accounts", "chat", "tracking"}:
        return
    for field in instance._meta.fields:
        if isinstance(field, FileField):
            item = getattr(instance, field.name)
            if item and item.name:
                transaction.on_commit(lambda storage=item.storage, name=item.name: _remove(storage, name))


@receiver(pre_save, sender=User)
def remove_replaced_avatar(sender, instance, **kwargs):
    if not instance.pk:
        return
    old = User.objects.filter(pk=instance.pk).first()
    if old and old.avatar and old.avatar.name != instance.avatar.name:
        transaction.on_commit(lambda: _remove(old.avatar.storage, old.avatar.name))


@receiver(pre_delete, sender=User)
def delete_billing_metadata(sender, instance, **kwargs):
    # Remove user identifiers from stored aliases/raw payloads as well as FK rows.
    from subscriptions.models import RevenueCatWebhookEvent
    if instance.role == User.ROLE_PARENT:
        from .models import ExternalAccountDeletion
        ExternalAccountDeletion.objects.get_or_create(app_user_id=str(instance.pk))
    RevenueCatWebhookEvent.objects.filter(user=instance).update(raw_payload={}, app_user_id="", error="")
    for row in RevenueCatWebhookEvent.objects.exclude(raw_payload={}):
        event = row.raw_payload.get("event", {})
        values = [event.get("app_user_id"), event.get("original_app_user_id"),
                  *(event.get("aliases") or []), *(event.get("transferred_from") or []), *(event.get("transferred_to") or [])]
        if str(instance.pk) in {str(v) for v in values}:
            row.raw_payload, row.app_user_id, row.error = {}, "", ""
            row.save(update_fields=["raw_payload", "app_user_id", "error"])
