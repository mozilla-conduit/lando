from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("headless_api", "0009_alter_automationjob_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="automationaction",
            name="action_type",
            field=models.CharField(
                choices=[
                    ("add-commit", "Add commit"),
                    ("add-commit-base64", "Add base64 commit"),
                    ("create-commit", "Create commit"),
                    ("tag", "Tag"),
                    ("merge-onto", "Merge onto"),
                    ("revert", "Revert commit"),
                ]
            ),
        ),
    ]
