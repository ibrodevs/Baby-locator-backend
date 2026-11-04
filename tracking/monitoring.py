from datetime import timedelta
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied
from .models import MonitorSession, RemoteDeviceCommand


class SessionClosed(APIException):
    status_code = 410
    default_detail = "Audio session expired or closed."


def close_session(session):
    session.status = MonitorSession.STATUS_CLOSED
    session.save(update_fields=["status"])
    RemoteDeviceCommand.objects.filter(child=session.child, status__in=["pending", "delivered"],
        command_type__in=["around_start", "webrtc_monitor_start"],
        payload__session_token=session.session_token).update(status="failed", error_message="session_closed")
    from .live_audio import live_audio_broker
    try:
        live_audio_broker.finish(session.session_token, child_id=session.child_id)
    except Exception:
        # Database closure still terminates peer polls even during a relay outage.
        import logging
        logging.getLogger(__name__).exception("HTTP relay closure unavailable")


def session_is_live(session):
    session.refresh_from_db(fields=["status", "expires_at", "consented_at", "parent_last_seen", "child_last_seen"])
    if session.status == "closed":
        return False
    now = timezone.now()
    cutoff = now - timedelta(seconds=settings.MONITOR_HEARTBEAT_TIMEOUT_SECONDS)
    expired = session.expires_at <= now
    if session.status == "active":
        expired = expired or any(seen is None or seen < cutoff for seen in [session.parent_last_seen, session.child_last_seen])
    if expired:
        close_session(session)
    return not expired


def authorized_session(user, token, *, allow_closed=False, require_consent=False):
    session = get_object_or_404(MonitorSession, session_token=token)
    if user.pk not in {session.parent_id, session.child_id}:
        raise PermissionDenied("This session belongs to another family.")
    if not session_is_live(session) and not allow_closed:
        raise SessionClosed()
    if require_consent and session.consented_at is None:
        raise PermissionDenied("Child confirmation is required before audio capture.")
    return session
