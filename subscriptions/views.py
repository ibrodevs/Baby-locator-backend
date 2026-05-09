import json

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import process_revenuecat_event, webhook_auth_is_valid


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
