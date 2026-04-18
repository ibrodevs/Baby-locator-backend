import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_initialized = False


def _ensure_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials

        key_path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_KEY", "")
        if not key_path or not os.path.exists(key_path):
            logger.warning("Firebase service account key not found at %s", key_path)
            return False

        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        return True
    except Exception as e:
        logger.error("Failed to initialize Firebase: %s", e)
        return False


def send_command_push(fcm_token: str, command_type: str):
    """Send a high-priority data-only FCM message to wake the child device."""
    if not fcm_token:
        return
    if not _ensure_firebase():
        logger.warning("Firebase not initialized, skipping FCM push")
        return

    try:
        from firebase_admin import messaging

        message = messaging.Message(
            data={"command_type": command_type},
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
            ),
            apns=messaging.APNSConfig(
                headers={"apns-priority": "10"},
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        content_available=True,
                        sound="default",
                    ),
                ),
            ),
        )
        response = messaging.send(message)
        logger.info("FCM %s push sent: %s", command_type, response)
    except Exception as e:
        logger.error("FCM send failed: %s", e)
