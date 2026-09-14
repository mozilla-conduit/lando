# Generated manually for job ownership during worker claims.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0066_landingjob_upliftjob_claimed_by"),
        ("headless_api", "0009_alter_automationjob_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="automationjob",
            name="claimed_by",
            field=models.ForeignKey(
            blank=True,
            null=True,
            on_delete=django.db.models.deletion.SET_NULL,
            to="main.worker",
        ),
        ),
    ]
