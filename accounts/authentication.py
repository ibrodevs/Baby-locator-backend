"""Legacy Lite envelopes remain readable, but never confer privileges."""
import hashlib
import hmac
from django.conf import settings
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


def _lite_signature(key):
    return hmac.new(settings.SECRET_KEY.encode(), f"lite:{key}".encode(), hashlib.sha256).hexdigest()


def build_lite_token(key):
    # Compatibility helper only: access is always read from server-owned grants.
    return f"lite.{key}.{_lite_signature(key)}"


class EditionTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        if key.startswith("lite."):
            parts = key.split(".")
            if len(parts) != 3 or not hmac.compare_digest(parts[2], _lite_signature(parts[1])):
                raise AuthenticationFailed("Invalid Lite token.")
            key = parts[1]
        return super().authenticate_credentials(key)
