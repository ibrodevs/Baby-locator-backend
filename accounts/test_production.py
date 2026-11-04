import tempfile
from datetime import timedelta
from django.test import override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework.authtoken.models import Token
from .models import User, InviteCode
from chat.models import Message
from subscriptions.models import RevenueCatWebhookEvent


class AccountSecurityTests(APITestCase):
    def setUp(self):
        self.parent=User.objects.create_user(username='parent-security',role='parent',is_premium=True,premium_expires_at=timezone.now()+timedelta(days=1))
        self.child=User.objects.create_user(username='child-security',role='child',parent=self.parent)
        self.token=Token.objects.create(user=self.parent)
        self.invite=InviteCode.objects.create(parent=self.parent,child=self.child,code='123456',expires_at=timezone.now()+timedelta(minutes=10))

    def test_pairing_single_use_and_rotates_old_token(self):
        old=Token.objects.create(user=self.child).key
        first=self.client.post('/api/auth/register-child/',{'code':'123456'},format='json')
        second=self.client.post('/api/auth/register-child/',{'code':'123456'},format='json')
        self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,400)
        self.assertNotEqual(first.data['token'],old)
        self.assertFalse(Token.objects.filter(key=old).exists())

    def test_invite_names_are_escaped(self):
        self.parent.display_name='<img src=x onerror=alert(1)>'; self.parent.save()
        response=self.client.get('/invite/123456/')
        self.assertNotIn(b'<img src=x onerror=alert(1)>',response.content)
        self.assertIn(b'&lt;img',response.content)

    def test_logout_revokes_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token '+self.token.key)
        self.assertEqual(self.client.post('/api/auth/logout/',{},format='json').status_code,204)
        self.assertEqual(self.client.get('/api/auth/me/').status_code,401)

    def test_weak_new_password_rejected(self):
        r=self.client.post('/api/auth/register/',{'username':'weak','password':'1234'},format='json')
        self.assertEqual(r.status_code,400)

    def test_private_files_require_family_auth(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            message=Message.objects.create(sender=self.parent,receiver=self.child,file=SimpleUploadedFile('file.txt',b'private'))
            path='/media/'+message.file.name
            self.assertEqual(self.client.get(path).status_code,401)
            self.client.force_authenticate(self.child)
            response=self.client.get(path);self.assertEqual(response.status_code,200); from django.core.signals import request_finished
            from django.db import close_old_connections
            request_finished.disconnect(close_old_connections)
            try: response.close()
            finally: request_finished.connect(close_old_connections)
            other=User.objects.create_user(username='other-security',role='parent')
            self.client.force_authenticate(other)
            self.assertEqual(self.client.get(path).status_code,404)

    def test_child_deletion_cleans_chat_file_and_event_pii(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            message=Message.objects.create(sender=self.parent,receiver=self.child,file=SimpleUploadedFile('private.txt',b'private'))
            storage,name=message.file.storage,message.file.name
            event=RevenueCatWebhookEvent.objects.create(event_id='pii',event_type='TEST',user=self.child,raw_payload={'event':{'app_user_id':str(self.child.pk)}})
            self.client.force_authenticate(self.parent)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.delete(f'/api/auth/children/{self.child.pk}/').status_code,204)
            self.assertFalse(storage.exists(name))
            event.refresh_from_db();self.assertEqual(event.raw_payload,{})
