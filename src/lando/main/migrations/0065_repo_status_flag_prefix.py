from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0064_alter_repo_force_push"),
    ]

    operations = [
        migrations.AddField(
            model_name="repo",
            name="status_flag_prefix",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Prefix of the Bugzilla status flags (e.g. `cf_status_firefox`) "
                    "that must be set on sec-high/sec-critical bugs before landing to "
                    "this repo. Leave empty to disable the security status-flag check "
                    "for this repo."
                ),
            ),
        ),
    ]
