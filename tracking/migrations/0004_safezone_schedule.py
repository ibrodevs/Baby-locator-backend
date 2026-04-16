from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0003_device_stats_and_app_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="safezone",
            name="active_days",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="safezone",
            name="schedule_type",
            field=models.CharField(
                choices=[("always", "Always"), ("days", "Specific days")],
                default="always",
                max_length=16,
            ),
        ),
    ]
