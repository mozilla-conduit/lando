# Generated by Django 5.1.7 on 2025-04-03 14:28

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0020_repo_pushlog_disabled"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repo",
            name="commit_flags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=django.contrib.postgres.fields.ArrayField(
                    base_field=models.CharField(blank=True, max_length=255), size=None
                ),
                blank=True,
                default=None,
                null=True,
                size=2,
            ),
        ),
    ]
