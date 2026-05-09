import hmac
import logging
from collections.abc import Iterable
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response

from accounts.models import User

from .models import RevenueCatWebhookEvent

logger = logging.getLogger(__name__)

PREMIUM_REQUIRED_DETAIL = "Family Security Pro subscription required."


def premium_required_response():
    return Response(
        {
            "detail": PREMIUM_REQUIRED_DETAIL,
            "code": "premium_required",
            "entitlement": settings.REVENUECAT_ENTITLEMENT_ID,
        },
        status=403,
    )


def has_premium_access(user, *, child=None):
    owner = subscription_owner_for(user, child=child)
    return bool(owner and owner.is_premium)


def subscription_owner_for(user, *, child=None):
    if user.role == User.ROLE_PARENT:
        return user
    if child is not None and getattr(child, "parent_id", None):
        return child.parent
    if user.role == User.ROLE_CHILD and getattr(user, "parent_id", None):
        return user.parent
    return None


def parent_can_add_child(parent):
    return parent.is_premium or parent.children.count() < 1


def webhook_auth_is_valid(header_value):
    expected = (settings.REVENUECAT_WEBHOOK_AUTH_HEADER or "").strip()
    if not expected:
        return bool(settings.DEBUG)
    actual = (header_value or "").strip()
    return hmac.compare_digest(actual, expected)


def process_revenuecat_event(payload):
    event = payload.get("event")
    if not isinstance(event, dict):
        raise ValueError("Missing event payload")

    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id or not event_type:
        raise ValueError("RevenueCat event id/type is required")

    app_user_id = _first_non_empty_string(
        event.get("app_user_id"),
        event.get("original_app_user_id"),
    )
    backend_user_id = _resolve_backend_user_id(event)
    user = User.objects.filter(id=backend_user_id).first() if backend_user_id else None

    with transaction.atomic():
        if RevenueCatWebhookEvent.objects.select_for_update().filter(event_id=event_id).exists():
            return {"status": "duplicate", "user_id": user.id if user else None}

        event_row = RevenueCatWebhookEvent.objects.create(
            event_id=event_id,
            event_type=event_type,
            app_user_id=app_user_id,
            environment=str(event.get("environment") or "").strip(),
            product_id=_event_product_id(event),
            entitlement_ids=_event_entitlement_ids(event),
            user=user,
            raw_payload=payload,
        )

        if user is None:
            logger.warning(
                "RevenueCat webhook ignored: no backend user for event_id=%s app_user_id=%s",
                event_id,
                app_user_id,
            )
            return {"status": "ignored", "reason": "unknown_user", "event_id": event_row.event_id}

        if not _event_targets_family_security(event):
            logger.info(
                "RevenueCat webhook skipped: event_id=%s does not target entitlement=%s",
                event_id,
                settings.REVENUECAT_ENTITLEMENT_ID,
            )
            return {"status": "ignored", "reason": "irrelevant_entitlement", "user_id": user.id}

        _apply_event_to_user(user, event)

    return {"status": "processed", "user_id": user.id, "is_premium": user.is_premium}


def _apply_event_to_user(user, event):
    event_time = _millis_to_datetime(event.get("event_timestamp_ms")) or timezone.now()
    expires_at = _millis_to_datetime(event.get("expiration_at_ms"))
    product_id = _event_product_id(event)
    is_premium = _event_grants_premium(event, product_id=product_id, expires_at=expires_at)

    user.is_premium = is_premium
    user.premium_entitlement = settings.REVENUECAT_ENTITLEMENT_ID if is_premium else ""
    user.premium_product_id = product_id
    user.premium_expires_at = expires_at if is_premium else None
    user.premium_updated_at = event_time
    user.save(
        update_fields=[
            "is_premium",
            "premium_entitlement",
            "premium_product_id",
            "premium_expires_at",
            "premium_updated_at",
        ]
    )


def _event_grants_premium(event, *, product_id, expires_at):
    if product_id in set(settings.REVENUECAT_LIFETIME_PRODUCT_IDS or []):
        return True

    if expires_at is not None:
        return expires_at > timezone.now()

    event_type = str(event.get("type") or "").upper()
    return event_type in {"INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION"}


def _event_targets_family_security(event):
    entitlement_id = str(event.get("entitlement_id") or "").strip()
    entitlement_ids = set(_event_entitlement_ids(event))
    expected_entitlement = settings.REVENUECAT_ENTITLEMENT_ID
    if entitlement_id == expected_entitlement:
        return True
    if expected_entitlement in entitlement_ids:
        return True

    product_id = _event_product_id(event)
    return product_id in set(settings.REVENUECAT_PREMIUM_PRODUCT_IDS or [])


def _event_entitlement_ids(event):
    raw = event.get("entitlement_ids") or []
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _event_product_id(event):
    return _first_non_empty_string(
        event.get("product_id"),
        event.get("new_product_id"),
    )


def _resolve_backend_user_id(event):
    candidates = []
    for key in ("app_user_id", "original_app_user_id"):
        candidates.append(event.get(key))

    aliases = event.get("aliases") or []
    if isinstance(aliases, Iterable) and not isinstance(aliases, (str, bytes)):
        candidates.extend(list(aliases))

    for candidate in candidates:
        parsed = _parse_backend_user_id(candidate)
        if parsed is not None:
            return parsed
    return None


def _parse_backend_user_id(value):
    raw = str(value or "").strip()
    if not raw or raw.startswith("$RCAnonymousID:"):
        return None
    if not raw.isdigit():
        return None
    parsed = int(raw)
    return parsed if parsed > 0 else None


def _millis_to_datetime(value):
    if value in (None, ""):
        return None
    try:
        timestamp = int(value) / 1000
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)


def _first_non_empty_string(*values):
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
