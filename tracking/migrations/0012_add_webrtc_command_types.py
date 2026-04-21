from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0011_add_monitor_session'),
    ]

    operations = [
        migrations.AlterField(
            model_name='remotedevicecommand',
            name='command_type',
            field=models.CharField(
                choices=[
                    ('loud', 'Loud'),
                    ('loud_stop', 'Loud Stop'),
                    ('around_start', 'Around Start'),
                    ('around_stop', 'Around Stop'),
                    ('sync_blocked_apps', 'Sync Blocked Apps'),
                    ('webrtc_monitor_start', 'WebRTC Monitor Start'),
                    ('webrtc_monitor_stop', 'WebRTC Monitor Stop'),
                ],
                max_length=32,
            ),
        ),
    ]
