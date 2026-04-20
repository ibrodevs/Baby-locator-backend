from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0008_add_loud_stop_command"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationupdate",
            name="charging",
            field=models.BooleanField(default=False),
        ),
    ]
