import json

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import build_lite_token, lite_app_key_is_valid

from .services import process_revenuecat_event, webhook_auth_is_valid


class LiteAccessTokenView(APIView):
    """Exchange a normal authenticated token for a signed Lite edition token.

    The paid app continues using its ordinary DRF token and RevenueCat rules.
    Only the Lite build knows the deployment-specific access key required to
    mint this signed token. No user premium fields are changed in the database.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not lite_app_key_is_valid(request.headers.get("X-Lite-App-Key")):
            return Response({"detail": "invalid lite app key"}, status=403)

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
