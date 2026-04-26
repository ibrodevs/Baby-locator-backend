from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0012_add_webrtc_command_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="devicestatus",
            name="accessibility_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="background_location_granted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="battery_optimization_disabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="location_permission_granted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="location_service_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="microphone_granted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="notifications_granted",
            field=models.BooleanField(default=False),
        ),
    ]
