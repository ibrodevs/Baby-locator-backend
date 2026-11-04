"""Server-authoritative subscription and family license policy."""
import hmac
import json
import logging
from datetime import datetime, timezone as dt_timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response

from accounts.models import User
from .models import CustomerEntitlement, LiteAccessGrant, RevenueCatWebhookEvent

logger = logging.getLogger(__name__)
PREMIUM_REQUIRED_DETAIL = "Family Security Pro subscription required."


class SubscriptionSyncError(Exception):
    """Transient/configuration error, safe to expose without upstream credentials."""


def premium_required_response():
    return Response({"detail": PREMIUM_REQUIRED_DETAIL, "code": "premium_required",
                     "entitlement": settings.REVENUECAT_ENTITLEMENT_ID}, status=403)


def subscription_owner_for(user, *, child=None):
    if user.role == User.ROLE_PARENT:
        return user
    target = child or user
    return target.parent if target.role == User.ROLE_CHILD and target.parent_id else None


def has_lite_access(user):
    owner = subscription_owner_for(user)
    return bool(owner and LiteAccessGrant.objects.filter(owner=owner, revoked_at__isnull=True,
                                                         expires_at__gt=timezone.now()).exists())


def has_premium_access(user, *, child=None):
    owner = subscription_owner_for(user, child=child)
    if owner is None:
        return False
    if has_lite_access(owner):
        return True
    if not owner.is_premium:
        return False
    if owner.premium_expires_at is not None:
        return owner.premium_expires_at > timezone.now()
    # Expiry-less legacy/admin grants must name an explicitly allowed lifetime product.
    return _product_matches_configured_ids(owner.premium_product_id, settings.REVENUECAT_LIFETIME_PRODUCT_IDS)


def parent_can_add_child(parent):
    return has_premium_access(parent) or parent.children.count() < 1


def can_view_location(user, *, child):
    owner = subscription_owner_for(user, child=child)
    return bool(owner and (has_premium_access(user, child=child) or owner.children.count() <= 1))


def webhook_auth_is_valid(header_value):
    expected = settings.REVENUECAT_WEBHOOK_AUTH_HEADER.strip()
    return bool(expected and hmac.compare_digest((header_value or "").strip(), expected))


def _millis_to_datetime(value):
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=dt_timezone.utc) if value is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _parse_backend_user_id(value):
    value = str(value or "")
    return int(value) if len(value) <= 19 and value.isascii() and value.isdigit() and 0 < int(value) < 2**63 else None


def _product_matches_configured_ids(product_id, configured_ids):
    # Exact store IDs, or a configured subscription ID with its own base plan.
    # Never match an arbitrary shared base-plan suffix such as ':monthly'.
    return any(product_id == item or product_id.startswith(item + ":") for item in configured_ids if item)


def _event_targets_family_security(event):
    return settings.REVENUECAT_ENTITLEMENT_ID in (event.get("entitlement_ids") or []) or event.get("entitlement_id") == settings.REVENUECAT_ENTITLEMENT_ID


def _event_grants_premium(event, *, product_id, expires_at):
    kind = event.get("type", "").upper()
    if kind in {"EXPIRATION"} or event.get("cancel_reason") == "CUSTOMER_SUPPORT":
        return False
    if kind not in {"INITIAL_PURCHASE", "RENEWAL", "NON_RENEWING_PURCHASE", "UNCANCELLATION", "CANCELLATION", "BILLING_ISSUE", "SUBSCRIPTION_EXTENDED", "TEMPORARY_ENTITLEMENT_GRANT", "SUBSCRIPTION_PAUSED"}:
        return False
    if expires_at is not None:
        return expires_at > timezone.now()
    return _product_matches_configured_ids(product_id, settings.REVENUECAT_LIFETIME_PRODUCT_IDS)


def _recalculate_user(user, at):
    active = [row for row in user.store_entitlements.all() if not row.revoked and
              (row.lifetime or row.expires_at and row.expires_at > timezone.now())]
    # Any lifetime entitlement dominates subscriptions, otherwise choose latest expiry.
    active.sort(key=lambda row: (row.lifetime, row.expires_at or at), reverse=True)
    best = active[0] if active else None
    user.is_premium = best is not None
    user.premium_entitlement = settings.REVENUECAT_ENTITLEMENT_ID if best else ""
    user.premium_product_id = best.product_id if best else ""
    user.premium_expires_at = None if best and best.lifetime else best.expires_at if best else None
    user.premium_updated_at = max(at, user.premium_updated_at or at)
    user.save(update_fields=["is_premium", "premium_entitlement", "premium_product_id", "premium_expires_at", "premium_updated_at"])


def sync_subscriber(user):
    """Only the server contacts RevenueCat; no client premium/receipt fields are trusted."""
    owner = subscription_owner_for(user)
    if owner is None:
        raise SubscriptionSyncError("A linked parent account is required.")
    key = settings.REVENUECAT_SECRET_API_KEY
    if not key:
        raise SubscriptionSyncError("Subscription server sync is not configured.")
    started_at = timezone.now()
    request = Request("https://api.revenuecat.com/v1/subscribers/" + quote(str(owner.id), safe=""),
                      headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=settings.REVENUECAT_HTTP_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read(2 * 1024 * 1024))
    except HTTPError as exc:
        if exc.code == 404:
            data = {"subscriber": {"entitlements": {}}}
        else:
            raise SubscriptionSyncError("Subscription provider is temporarily unavailable.") from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise SubscriptionSyncError("Subscription provider is temporarily unavailable.") from None
    subscriber = data.get("subscriber")
    if not isinstance(subscriber, dict) or not isinstance(subscriber.get("entitlements", {}), dict):
        raise SubscriptionSyncError("Subscription provider returned an invalid response.")
    entitlement = subscriber.get("entitlements", {}).get(settings.REVENUECAT_ENTITLEMENT_ID)
    with transaction.atomic():
        owner = User.objects.select_for_update().get(pk=owner.pk)
        if owner.premium_updated_at and owner.premium_updated_at > started_at:
            return owner  # A newer webhook/sync already won; don't overwrite it.
        owner.store_entitlements.update(revoked=True)
        if isinstance(entitlement, dict):
            product = str(entitlement.get("product_identifier") or "")
            subscription = subscriber.get("subscriptions", {}).get(product, {})
            sandbox = subscription.get("is_sandbox", False)
            environment = "SANDBOX" if sandbox else "PRODUCTION"
            # For non-subscription purchases look up the matching purchase's environment.
            purchases = subscriber.get("non_subscriptions", {}).get(product, [])
            if purchases:
                latest = purchases[-1]
                environment = "SANDBOX" if latest.get("is_sandbox") else "PRODUCTION"
            expiry = _iso_datetime(entitlement.get("expires_date"))
            grace = _iso_datetime(subscription.get("grace_period_expires_date") or entitlement.get("grace_period_expires_date"))
            if grace and (expiry is None or grace > expiry):
                expiry = grace
            lifetime = expiry is None and _product_matches_configured_ids(product, settings.REVENUECAT_LIFETIME_PRODUCT_IDS)
            refunded = bool(subscription.get("refunded_at"))
            if environment in settings.REVENUECAT_ALLOWED_ENVIRONMENTS and product:
                CustomerEntitlement.objects.update_or_create(user=owner, product_id=product,
                    defaults={"expires_at": expiry, "lifetime": lifetime, "revoked": refunded or not (lifetime or expiry and expiry > timezone.now()), "updated_at": started_at})
        owner.premium_synced_at = started_at
        owner.save(update_fields=["premium_synced_at"])
        _recalculate_user(owner, started_at)
    return owner


def _iso_datetime(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=dt_timezone.utc)
    except (ValueError, TypeError):
        raise SubscriptionSyncError("Subscription provider returned an invalid expiry.") from None


def process_revenuecat_event(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), dict):
        raise ValueError("Missing event payload")
    event = payload["event"]
    for key in ("aliases", "entitlement_ids", "transferred_from", "transferred_to"):
        if key in event and (not isinstance(event[key], list) or len(event[key]) > 100 or any(not isinstance(v, str) for v in event[key])):
            raise ValueError("Invalid webhook identity/entitlement list")
    event_id, kind = str(event.get("id") or ""), str(event.get("type") or "").upper()
    if not event_id or len(event_id) > 128 or not kind or len(kind) > 64:
        raise ValueError("RevenueCat event id/type is required")
    # Store only the fields needed for safe replay, not the entire customer's billing metadata.
    safe_event = {k: event[k] for k in ("id", "type", "app_user_id", "original_app_user_id", "aliases", "product_id", "entitlement_ids", "entitlement_id", "expiration_at_ms", "grace_period_expiration_at_ms", "event_timestamp_ms", "environment", "app_id", "cancel_reason", "transferred_from", "transferred_to") if k in event}
    row, _ = RevenueCatWebhookEvent.objects.get_or_create(event_id=event_id, defaults={
        "event_type": kind, "app_user_id": str(event.get("app_user_id") or "")[:128],
        "environment": str(event.get("environment") or "")[:32], "raw_payload": {"event": safe_event}})
    if row.status in {"processed", "ignored"}:
        return {"status": "duplicate"}
    reason = ""
    if event.get("environment") not in settings.REVENUECAT_ALLOWED_ENVIRONMENTS:
        reason = "environment_not_allowed"
    elif not settings.REVENUECAT_APP_IDS or event.get("app_id") not in settings.REVENUECAT_APP_IDS:
        reason = "app_not_allowed"
    if reason:
        row.status, row.error = "ignored", reason
        row.save(update_fields=["status", "error"])
        return {"status": "ignored", "reason": reason}
    supported = {"INITIAL_PURCHASE", "RENEWAL", "CANCELLATION", "UNCANCELLATION", "NON_RENEWING_PURCHASE", "EXPIRATION", "BILLING_ISSUE", "SUBSCRIPTION_PAUSED", "SUBSCRIPTION_EXTENDED", "TEMPORARY_ENTITLEMENT_GRANT"}
    if kind not in supported | {"TRANSFER", "PRODUCT_CHANGE", "REFUND_REVERSED"}:
        row.status, row.error = "ignored", "unsupported_event"
        row.save(update_fields=["status", "error"])
        return {"status": "ignored", "reason": "unsupported_event"}
    candidates = [event.get("app_user_id"), event.get("original_app_user_id"), *(event.get("aliases") or [])]
    if kind == "TRANSFER":
        candidates = [*(event.get("transferred_from") or []), *(event.get("transferred_to") or [])]
    ids = {n for value in candidates if (n := _parse_backend_user_id(value)) is not None}
    users = list(User.objects.filter(pk__in=ids, role=User.ROLE_PARENT).order_by("pk"))
    if not users:
        row.status, row.error = "pending", "unknown_user"
        row.save(update_fields=["status", "error"])
        raise SubscriptionSyncError("Webhook user is not linked yet; retry required.")
    if kind == "TRANSFER":
        for owner in users:
            sync_subscriber(owner)
        row.status, row.error = "processed", ""
        row.save(update_fields=["status", "error"])
        return {"status": "processed"}
    if kind in {"PRODUCT_CHANGE", "REFUND_REVERSED"}:
        sync_subscriber(users[0])
        row.status = "processed"
        row.save(update_fields=["status"])
        return {"status": "processed"}
    # Prefer the actual current user ID; aliases are fallback only, never grant all aliases.
    primary = _parse_backend_user_id(event.get("app_user_id"))
    if primary not in {u.pk for u in users}:
        owner = sync_subscriber(users[0])
        row.status = "processed"
        row.save(update_fields=["status"])
        return {"status": "processed", "user_id": owner.pk, "is_premium": has_premium_access(owner)}
    owner_id = primary
    event_at = _millis_to_datetime(event.get("event_timestamp_ms"))
    if not event_at or event_at > timezone.now() + timezone.timedelta(minutes=5):
        raise ValueError("Invalid event timestamp")
    product = str(event.get("product_id") or "")[:200]
    with transaction.atomic():
        owner = User.objects.select_for_update().get(pk=owner_id)
        row = RevenueCatWebhookEvent.objects.select_for_update().get(pk=row.pk)
        if row.status == "processed":
            return {"status": "duplicate"}
        if _event_targets_family_security(event) and product:
            current = CustomerEntitlement.objects.filter(user=owner, product_id=product).first()
            # A full provider snapshot supersedes any older per-product event.
            cutoff = max([t for t in (owner.premium_synced_at, current.updated_at if current else None) if t], default=None)
            if not cutoff or event_at >= cutoff:
                expiry = _millis_to_datetime(event.get("expiration_at_ms"))
                if kind == "BILLING_ISSUE":
                    grace = _millis_to_datetime(event.get("grace_period_expiration_at_ms"))
                    if grace and (expiry is None or grace > expiry):
                        expiry = grace
                if current and current.expires_at and kind in {"BILLING_ISSUE", "SUBSCRIPTION_PAUSED", "CANCELLATION"} and (expiry is None or current.expires_at > expiry):
                    # Cancellation/pausing do not shorten an already granted paid/grace period.
                    # Refunds still revoke below; EXPIRATION and provider sync can reduce access.
                    expiry = current.expires_at
                granted = _event_grants_premium(event, product_id=product, expires_at=expiry)
                CustomerEntitlement.objects.update_or_create(user=owner, product_id=product, defaults={
                    "expires_at": expiry, "lifetime": expiry is None and granted,
                    "revoked": not granted, "updated_at": event_at})
                _recalculate_user(owner, event_at)
        row.user, row.product_id, row.status, row.error = owner, product[:128], "processed", ""
        row.save(update_fields=["user", "product_id", "status", "error"])
    return {"status": "processed", "user_id": owner.id, "is_premium": has_premium_access(owner)}
