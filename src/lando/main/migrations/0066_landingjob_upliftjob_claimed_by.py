# Generated manually for job ownership during landing worker claims.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0065_alter_landingjob_status_alter_upliftjob_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="landingjob",
            name="claimed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="main.worker",
            ),
        ),
        migrations.AddField(
            model_name="upliftjob",
            name="claimed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="main.worker",
            ),
        ),
    ]
