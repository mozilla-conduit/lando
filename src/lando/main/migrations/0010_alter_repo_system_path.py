# Generated by Django 5.1.3 on 2024-11-25 04:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0009_profile_encrypted_phabricator_api_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repo",
            name="system_path",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
