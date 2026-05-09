from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_joined_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_premium",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="premium_entitlement",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="user",
            name="premium_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="premium_product_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="user",
            name="premium_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
