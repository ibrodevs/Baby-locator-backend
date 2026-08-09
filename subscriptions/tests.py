from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User


class PaidAndLiteAccessTests(APITestCase):
    def setUp(self):
        self.parent = User.objects.create_user(
            username="free-parent",
            password="pass1234",
            role=User.ROLE_PARENT,
            is_premium=False,
        )
        self.child = User.objects.create_user(
            username="child-user",
            password="pass1234",
            role=User.ROLE_CHILD,
            parent=self.parent,
        )
        self.token = Token.objects.create(user=self.parent)
        self.location_url = f"/api/children/{self.child.id}/location/"
        self.exchange_url = "/api/revenuecat/lite-token/"

    def _auth(self, token_value):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token_value}")

    def test_paid_non_premium_keeps_existing_restriction(self):
        self._auth(self.token.key)
        response = self.client.get(self.location_url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data.get("code"), "premium_required")

    def test_paid_premium_keeps_existing_access(self):
        self.parent.is_premium = True
        self.parent.save(update_fields=["is_premium"])
        self._auth(self.token.key)

        # There is no location in this test, so 404 proves the request passed
        # the premium gate instead of being rejected with premium_required.
        response = self.client.get(self.location_url)
        self.assertEqual(response.status_code, 404)

    def test_lite_token_exchange_requires_lite_edition_header(self):
        self._auth(self.token.key)
        response = self.client.post(self.exchange_url, {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_lite_non_premium_gets_full_access_without_db_premium_change(self):
        self._auth(self.token.key)
        response = self.client.post(
            self.exchange_url,
            {},
            format="json",
            HTTP_X_APP_EDITION="lite",
        )
        self.assertEqual(response.status_code, 200)
        lite_token = response.data["token"]
        self.assertTrue(lite_token.startswith("lite."))

        self._auth(lite_token)
        premium_response = self.client.get(self.location_url)
        self.assertEqual(premium_response.status_code, 404)

        self.parent.refresh_from_db()
        self.assertFalse(self.parent.is_premium)

    def test_tampered_lite_token_is_rejected(self):
        self._auth(self.token.key)
        response = self.client.post(
            self.exchange_url,
            {},
            format="json",
            HTTP_X_APP_EDITION="lite",
        )
        lite_token = response.data["token"]
        tampered = f"{lite_token[:-1]}{'0' if lite_token[-1] != '0' else '1'}"

        self._auth(tampered)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)
