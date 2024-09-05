# Generated by Django 5.1 on 2024-09-05 15:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0006_repo_scm"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repo",
            name="system_path",
            field=models.FilePathField(
                allow_folders=True,
                blank=True,
                default="",
                max_length=255,
                path="/files/repos",
            ),
        ),
    ]
