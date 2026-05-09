from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RevenueCatWebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.CharField(db_index=True, max_length=128, unique=True)),
                ("event_type", models.CharField(db_index=True, max_length=64)),
                ("app_user_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("environment", models.CharField(blank=True, default="", max_length=32)),
                ("product_id", models.CharField(blank=True, default="", max_length=128)),
                ("entitlement_ids", models.JSONField(blank=True, default=list)),
                ("raw_payload", models.JSONField(blank=True, default=dict)),
                ("processed_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="revenuecat_webhook_events", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
