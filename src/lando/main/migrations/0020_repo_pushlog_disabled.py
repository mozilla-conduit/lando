# Generated by Django 5.1.4 on 2025-02-07 02:24

from django.db import migrations, models


def disable_pushlog_for_hg_repos(apps, schema_editor):  # noqa: ANN001
    """Disable the Lando PushLog for any pre-existing Hg repo."""
    Repo = apps.get_model("main", "Repo")
    for repo in Repo.objects.filter(scm_type="hg"):
        repo.pushlog_disabled = True
        repo.save()


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0019_alter_repo_short_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="repo",
            name="pushlog_disabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(disable_pushlog_for_hg_repos, migrations.RunPython.noop),
    ]
