# Generated by Django 5.1.3 on 2024-11-25 01:27

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0012_rename_push_bookmark_repo_push_target"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repo",
            name="scm_type",
            field=models.CharField(
                blank=True,
                choices=[("git", "Git"), ("hg", "Mercurial")],
                default=None,
                max_length=3,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="worker",
            name="scm",
            field=models.CharField(
                choices=[("git", "Git"), ("hg", "Mercurial")],
                default="hg",
                max_length=3,
            ),
        ),
    ]