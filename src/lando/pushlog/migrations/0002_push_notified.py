# Generated by Django 5.1.4 on 2025-03-25 23:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pushlog", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="push",
            name="notified",
            field=models.BooleanField(default=False),
        ),
    ]
