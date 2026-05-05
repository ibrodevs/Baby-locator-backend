from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0014_appicon"),
    ]

    operations = [
        migrations.AlterField(
            model_name="alert",
            name="alert_type",
            field=models.CharField(
                choices=[
                    ("location_update", "Location Update"),
                    ("battery_low", "Battery Low"),
                    ("safe_zone_exit", "Safe Zone Exit"),
                    ("sos", "SOS"),
                    ("chat_message", "Chat Message"),
                    ("task_assigned", "Task Assigned"),
                ],
                max_length=32,
            ),
        ),
    ]
