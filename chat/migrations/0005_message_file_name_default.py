from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0004_add_file_to_message"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="file_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
