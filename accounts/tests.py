from io import StringIO
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User, InviteCode
from tracking.models import LocationUpdate, AroundAudioClip
from tracking.live_audio import LiveAudioBroker

class AccountComplianceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.parent = User.objects.create_user(
            username="parent_compliance",
            password="TestPassword123!",
            role=User.ROLE_PARENT,
            display_name="Test Parent",
        )
        self.child = User.objects.create_user(
            username="child_compliance",
            password="TestPassword123!",
            role=User.ROLE_CHILD,
            display_name="Test Child",
        )
        self.child.parent = self.parent
        self.child.save()

    def test_unauthenticated_cannot_delete_account(self):
        response = self.client.delete("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_parent_account_deletion_cascades_and_cleans_files(self):
        # Create avatar files
        avatar_file = SimpleUploadedFile("avatar.png", b"fake_avatar_content", content_type="image/png")
        self.parent.avatar = avatar_file
        self.parent.save()

        child_avatar = SimpleUploadedFile("child.png", b"fake_child_avatar", content_type="image/png")
        self.child.avatar = child_avatar
        self.child.save()

        # Create audio clip
        audio_file = SimpleUploadedFile("clip.m4a", b"fake_audio_content", content_type="audio/mp4")
        clip = AroundAudioClip.objects.create(
            child=self.child,
            session_token="session_123",
            audio=audio_file,
            duration_seconds=10,
        )

        # Create location update with address
        LocationUpdate.objects.create(
            child=self.child,
            lat=37.7749,
            lng=-122.4194,
            address="123 Market St, San Francisco, CA",
        )

        self.client.force_authenticate(user=self.parent)
        response = self.client.delete("/api/auth/me/")
        self.assertEqual(response.status_code, 204)

        # Verify parent and linked child are deleted
        self.assertFalse(User.objects.filter(username="parent_compliance").exists())
        self.assertFalse(User.objects.filter(username="child_compliance").exists())
        self.assertFalse(LocationUpdate.objects.filter(address="123 Market St, San Francisco, CA").exists())
        self.assertFalse(AroundAudioClip.objects.filter(session_token="session_123").exists())

    def test_child_account_deletion(self):
        self.client.force_authenticate(user=self.child)
        response = self.client.delete("/api/auth/me/")
        self.assertEqual(response.status_code, 204)

        self.assertFalse(User.objects.filter(username="child_compliance").exists())
        # Parent still exists
        self.assertTrue(User.objects.filter(username="parent_compliance").exists())

    def test_create_play_review_accounts_command_idempotent(self):
        out = StringIO()
        call_command(
            "create_play_review_accounts",
            parent_username="test_play_parent",
            parent_password="Pass123!Parent",
            child_username="test_play_child",
            child_password="Pass123!Child",
            stdout=out,
        )
        output = out.getvalue()
        self.assertIn("Google Play reviewer accounts ready", output)

        parent = User.objects.get(username="test_play_parent")
        child = User.objects.get(username="test_play_child")
        self.assertTrue(parent.is_premium)
        self.assertEqual(child.parent_id, parent.id)

        # Rerun command to verify idempotency
        out2 = StringIO()
        call_command(
            "create_play_review_accounts",
            parent_username="test_play_parent",
            parent_password="Pass123!Parent",
            child_username="test_play_child",
            child_password="Pass123!Child",
            stdout=out2,
        )
        self.assertIn("Verified Existing", out2.getvalue())

    def test_live_audio_session_isolation(self):
        broker = LiveAudioBroker()
        # Child 1 starts session
        session = broker.get_or_create("shared_token_xyz", child_id=101)
        self.assertEqual(session.child_id, 101)

        # Child 2 attempts to claim the same session token
        with self.assertRaises(PermissionError):
            broker.get_or_create("shared_token_xyz", child_id=202)


class TestModeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(IS_TEST=True)
    def test_status_when_is_test_true(self):
        response = self.client.get("/api/auth/test-mode/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_test": True})

    @override_settings(IS_TEST=False)
    def test_status_when_is_test_false(self):
        response = self.client.get("/api/auth/test-mode/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_test": False})

    @override_settings(IS_TEST=False)
    def test_login_as_premium_forbidden_when_test_disabled(self):
        response = self.client.post("/api/auth/login-as-premium/", {})
        self.assertEqual(response.status_code, 403)
        self.assertIn("detail", response.json())

    @override_settings(IS_TEST=True)
    def test_login_as_premium_success_and_can_add_children(self):
        response = self.client.post("/api/auth/login-as-premium/", {})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("token", data)
        self.assertIn("user", data)

        user_data = data["user"]
        self.assertEqual(user_data["role"], "parent")
        self.assertTrue(user_data["is_premium"])
        self.assertEqual(user_data["premium_entitlement"], "family_security_pro")
        self.assertIsNotNone(user_data["premium_expires_at"])

        # Verify user in DB
        from subscriptions.services import parent_can_add_child
        user = User.objects.get(username="test_premium_parent")
        self.assertEqual(user.role, User.ROLE_PARENT)
        self.assertTrue(user.is_premium)
        self.assertTrue(parent_can_add_child(user))

        # Test authenticated child creation
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {data['token']}")
        res1 = self.client.post(
            "/api/auth/children/",
            {"display_name": "Test Kid 1", "gender": "boy"},
            format="json",
        )
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post(
            "/api/auth/children/",
            {"display_name": "Test Kid 2", "gender": "girl"},
            format="json",
        )
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(user.children.count(), 2)

