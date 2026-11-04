from django.conf import settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from accounts.serializers import UserSerializer
from accounts.authentication import build_lite_token
from .services import (SubscriptionSyncError, has_lite_access, has_premium_access,
                       process_revenuecat_event, sync_subscriber, webhook_auth_is_valid)


class RevenueCatConfigView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"android_api_key": settings.REVENUECAT_PUBLIC_API_KEY_ANDROID,
            "ios_api_key": settings.REVENUECAT_PUBLIC_API_KEY_IOS,
            "api_key": settings.REVENUECAT_PUBLIC_API_KEY_FALLBACK,
            "entitlement_id": settings.REVENUECAT_ENTITLEMENT_ID,
            "premium_product_ids": settings.REVENUECAT_PREMIUM_PRODUCT_IDS})


class LiteAccessTokenView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "integrity"

    def post(self, request):
        # An existing server-owned license may be reused. A header is never evidence.
        if not has_lite_access(request.user):
            return Response({"detail": "A server-issued Lite license is required.",
                             "code": "lite_license_required"}, status=403)
        return Response({"token": build_lite_token(request.auth.key), "edition": "lite",
                         "is_premium": has_premium_access(request.user)})


class SubscriptionSyncView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "subscription_sync"

    def post(self, request):
        try:
            sync_subscriber(request.user)
        except SubscriptionSyncError as exc:
            return Response({"detail": str(exc), "code": "subscription_sync_unavailable"}, status=503)
        request.user.refresh_from_db()
        return Response(UserSerializer(request.user, context={"request": request}).data)


class RevenueCatWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []  # Authenticated server-to-server traffic must not hit mobile IP quotas.

    def post(self, request):
        if not webhook_auth_is_valid(request.headers.get("Authorization")):
            return Response({"detail": "invalid webhook authorization"}, status=401)
        try:
            result = process_revenuecat_event(request.data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except SubscriptionSyncError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response(result)
