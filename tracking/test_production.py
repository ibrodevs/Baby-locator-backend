from datetime import timedelta
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import User
from .models import MonitorSession, SafeZone, RemoteDeviceCommand


class TrackingSecurityTests(APITestCase):
    def setUp(self):
        self.parent=User.objects.create_user(username='p',role='parent',is_premium=True,premium_expires_at=timezone.now()+timedelta(days=1))
        self.child=User.objects.create_user(username='c',role='child',parent=self.parent)
        self.other=User.objects.create_user(username='o',role='parent',is_premium=True,premium_expires_at=timezone.now()+timedelta(days=1))
        self.session=MonitorSession.objects.create(parent=self.parent,child=self.child,session_token='test-session')
        self.client.force_authenticate(self.parent)

    def test_stranger_cannot_stop_or_signal(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post('/api/monitor/deactivate/',{'child_id':self.child.pk},format='json').status_code,404)
        self.assertEqual(self.client.post('/api/monitor/deactivate/',{'session_token':self.session.session_token},format='json').status_code,403)
        self.assertFalse(RemoteDeviceCommand.objects.exists())

    def test_owner_can_stop_after_premium_revoked(self):
        self.parent.is_premium=False; self.parent.save()
        self.assertEqual(self.client.post('/api/monitor/deactivate/',{'session_token':self.session.session_token},format='json').status_code,200)
        self.session.refresh_from_db(); self.assertEqual(self.session.status,'closed')

    def test_child_can_stop(self):
        self.client.force_authenticate(self.child)
        self.assertEqual(self.client.post('/api/monitor/deactivate/',{'session_token':self.session.session_token},format='json').status_code,200)

    def test_child_can_read_but_not_modify_parent_zone(self):
        zone=SafeZone.objects.create(parent=self.parent,name='home',lat=1,lng=1,radius=100)
        self.client.force_authenticate(self.child)
        self.assertEqual(self.client.get('/api/safe-zones/').status_code,200)
        self.assertEqual(self.client.delete(f'/api/safe-zones/{zone.pk}/').status_code,403)

    def test_invalid_coordinates_rejected(self):
        self.client.force_authenticate(self.child)
        self.assertEqual(self.client.post('/api/locations/',{'lat':1234,'lng':9999,'battery':900},format='json').status_code,400)

    def test_stale_fix_keeps_original_capture_time(self):
        self.client.force_authenticate(self.child)
        at=timezone.now()-timedelta(days=1)
        r=self.client.post('/api/locations/',{'lat':1,'lng':1,'captured_at':at.isoformat(),'is_cached':True},format='json')
        self.assertEqual(r.status_code,201)
        self.assertTrue(r.data['is_cached'])
        self.assertEqual(self.child.alerts.count(),0)

    def test_only_child_can_consent_and_offer_requires_consent(self):
        url='/api/monitor/consent/'
        body={'session_token':self.session.session_token,'approved':True}
        self.assertEqual(self.client.post(url,body,format='json').status_code,403)
        self.client.force_authenticate(self.child)
        signal={'session_token':self.session.session_token,'type':'offer','payload':{'sdp':'test'},'message_id':'m1'}
        self.assertEqual(self.client.post('/api/monitor/signal/send/',signal,format='json').status_code,409)
        self.assertEqual(self.client.post(url,body,format='json').status_code,200)
        self.assertEqual(self.client.post('/api/monitor/signal/send/',signal,format='json').status_code,201)
        self.assertEqual(self.client.post('/api/monitor/signal/send/',signal,format='json').status_code,201)
        self.assertEqual(self.session.messages.count(),1)

    def test_expired_session_is_closed(self):
        self.session.expires_at=timezone.now()-timedelta(seconds=1);self.session.save()
        r=self.client.get('/api/monitor/signal/poll/',{'session_token':self.session.session_token})
        self.assertEqual(r.data['session_status'],'closed')

    def test_command_is_redelivered_after_lease(self):
        command=RemoteDeviceCommand.objects.create(child=self.child,created_by=self.parent,command_type='loud')
        self.client.force_authenticate(self.child)
        self.assertEqual(len(self.client.get('/api/device-commands/pending/').data),1)
        self.assertEqual(len(self.client.get('/api/device-commands/pending/').data),0)
        command.refresh_from_db();command.delivered_at=timezone.now()-timedelta(seconds=30);command.save()
        self.assertEqual(len(self.client.get('/api/device-commands/pending/').data),1)

    def test_expired_start_not_delivered(self):
        RemoteDeviceCommand.objects.create(child=self.child,created_by=self.parent,command_type='loud',expires_at=timezone.now()-timedelta(seconds=1))
        self.client.force_authenticate(self.child)
        self.assertEqual(self.client.get('/api/device-commands/pending/').data,[])
