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


def send_command_push(fcm_token: str, command_type: str, extra_data=None):
    """Send a high-priority data-only FCM message to wake the child device."""
    if not fcm_token:
        return
    if not _ensure_firebase():
        logger.warning("Firebase not initialized, skipping FCM push")
        return

    try:
        from firebase_admin import messaging

        data = {"command_type": command_type}
        if extra_data:
            data.update({k: str(v) for k, v in extra_data.items() if v is not None})

        message = messaging.Message(
            data=data,
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
            ),
            apns=messaging.APNSConfig(
                headers={
                    "apns-priority": "5",
                    "apns-push-type": "background",
                },
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        content_available=True,
                    ),
                ),
            ),
        )
        response = messaging.send(message)
        logger.info("FCM %s push sent: %s", command_type, response)
    except Exception as e:
        logger.error("FCM send failed: %s", e)


def send_notification_push(fcm_token: str, notification_type: str, title: str, body: str, extra_data=None):
    """Send a high-priority notification FCM message to the parent device."""
    if not fcm_token:
        return
    if not _ensure_firebase():
        logger.warning("Firebase not initialized, skipping FCM push")
        return

    try:
        from firebase_admin import messaging

        data = {
            "notification_type": notification_type,
            "title": title,
            "body": body,
        }
        if extra_data:
            data.update({k: str(v) for k, v in extra_data.items() if v is not None})

        if notification_type == "sos":
            # Android must receive SOS as a data-first push so the background
            # handler can raise a local full-screen intent notification even
            # when the app is backgrounded or terminated. iOS still gets a
            # visible APNS alert via the platform-specific payload below.
            message = messaging.Message(
                data=data,
                token=fcm_token,
                android=messaging.AndroidConfig(
                    priority="high",
                ),
                apns=messaging.APNSConfig(
                    headers={
                        "apns-priority": "10",
                        "apns-push-type": "alert",
                    },
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(
                                title=title,
                                body=body,
                            ),
                            sound="default",
                            content_available=True,
                        ),
                    ),
                ),
            )
            response = messaging.send(message)
            logger.info("FCM notification %s push sent: %s", notification_type, response)
            return

        message = messaging.Message(
            data=data,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="kid_security_activity_alerts",
                    sound="default",
                ),
            ),
            apns=messaging.APNSConfig(
                headers={
                    "apns-priority": "10",
                    "apns-push-type": "alert",
                },
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        alert=messaging.ApsAlert(
                            title=title,
                            body=body,
                        ),
                        sound="default",
                    ),
                ),
            ),
        )
        response = messaging.send(message)
        logger.info("FCM notification %s push sent: %s", notification_type, response)
    except Exception as e:
        logger.error("FCM notification send failed: %s", e)
