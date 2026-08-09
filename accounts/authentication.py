import hashlib
import hmac

from django.conf import settings
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


LITE_TOKEN_PREFIX = "lite"


def _lite_signature(token_key: str) -> str:
    """Sign Lite credentials with Django's existing SECRET_KEY."""
    signing_key = settings.SECRET_KEY.encode("utf-8")
    payload = f"{LITE_TOKEN_PREFIX}:{token_key}".encode("utf-8")
    return hmac.new(signing_key, payload, hashlib.sha256).hexdigest()


def build_lite_token(token_key: str) -> str:
    """Wrap an existing DRF token in a backend-signed Lite credential."""
    return f"{LITE_TOKEN_PREFIX}.{token_key}.{_lite_signature(token_key)}"


class EditionTokenAuthentication(TokenAuthentication):
    """Authenticate both the existing paid app and Baby Locator Lite.

    Paid/legacy clients keep using ``Token <key>`` and behave exactly as before.
    Lite uses ``Token lite.<key>.<signature>``. A valid Lite signature only sets
    a transient flag on the request user; it never changes premium fields in DB.
    """

    def authenticate_credentials(self, key):
        raw_key = key
        is_lite = False

        if key.startswith(f"{LITE_TOKEN_PREFIX}."):
            parts = key.split(".", 2)
            if len(parts) != 3:
                raise AuthenticationFailed("Invalid Lite token.")

            _, token_key, signature = parts
            expected = _lite_signature(token_key)
            if not hmac.compare_digest(signature, expected):
                raise AuthenticationFailed("Invalid Lite token signature.")

            raw_key = token_key
            is_lite = True

        user, token = super().authenticate_credentials(raw_key)
        if is_lite:
            setattr(user, "_lite_full_access", True)
        return user, token
