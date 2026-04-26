from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_gender_invitecode"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="joined_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
