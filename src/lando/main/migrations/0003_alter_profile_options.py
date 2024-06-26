# Generated by Django 5.0.6 on 2024-06-06 15:30

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0002_profile"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="profile",
            options={
                "permissions": (
                    ("scm_allow_direct_push", "SCM_ALLOW_DIRECT_PUSH"),
                    ("scm_conduit", "SCM_CONDUIT"),
                    ("scm_firefoxci", "SCM_FIREFOXCI"),
                    ("scm_l10n_infra", "SCM_L10N_INFRA"),
                    ("scm_level_1", "SCM_LEVEL_1"),
                    ("scm_level_2", "SCM_LEVEL_2"),
                    ("scm_level_3", "SCM_LEVEL_3"),
                    ("scm_nss", "SCM_NSS"),
                    ("scm_versioncontrol", "SCM_VERSIONCONTROL"),
                )
            },
        ),
    ]
