from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0013_devicestatus_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AppIcon",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("package_name", models.CharField(max_length=255)),
                ("icon_b64", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "child",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="app_icons",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["package_name"],
                "unique_together": {("child", "package_name")},
            },
        ),
    ]
