from django.conf import settings
import json

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import build_lite_token

from .services import process_revenuecat_event, webhook_auth_is_valid


class RevenueCatConfigView(APIView):
    """Returns the public RevenueCat configuration (API keys, entitlement ID, offerings).

    Allows the mobile client to fetch RevenueCat API keys dynamically from the server
    without requiring --dart-define compilation parameters or embedding production keys.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "android_api_key": settings.REVENUECAT_PUBLIC_API_KEY_ANDROID,
                "ios_api_key": settings.REVENUECAT_PUBLIC_API_KEY_IOS,
                "api_key": settings.REVENUECAT_PUBLIC_API_KEY_FALLBACK
                or settings.REVENUECAT_PUBLIC_API_KEY_ANDROID,
                "entitlement_id": settings.REVENUECAT_ENTITLEMENT_ID,
                "premium_product_ids": settings.REVENUECAT_PREMIUM_PRODUCT_IDS,
            },
            status=200,
        )



class LiteAccessTokenView(APIView):
    """Exchange a normal authenticated token for a signed Lite edition token.

    The paid app continues using its ordinary DRF token and RevenueCat rules.
    Baby Locator Lite identifies itself with ``X-App-Edition: lite`` and gets a
    signed Lite token. No user premium fields are changed in the database.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        edition = (request.headers.get("X-App-Edition") or "").strip().lower()
        if edition != "lite":
            return Response({"detail": "lite edition required"}, status=403)

        token_key = getattr(request.auth, "key", "")
        if not token_key:
            return Response({"detail": "token authentication required"}, status=400)

        return Response(
            {
                "token": build_lite_token(token_key),
                "edition": "lite",
            },
            status=200,
        )


class RevenueCatWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not webhook_auth_is_valid(request.headers.get("Authorization")):
            return Response({"detail": "invalid webhook authorization"}, status=401)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return Response({"detail": "invalid json"}, status=400)

        try:
            result = process_revenuecat_event(payload)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(result, status=200)
