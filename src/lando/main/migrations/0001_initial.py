# Generated by Django 5.0.6 on 2024-05-16 18:10

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ConfigurationVariable",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.TextField(unique=True)),
                ("raw_value", models.TextField(blank=True, default="")),
                (
                    "variable_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("BOOL", "Boolean"),
                            ("INT", "Integer"),
                            ("STR", "String"),
                        ],
                        default="STR",
                        max_length=4,
                        null=True,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="DiffWarning",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revision_id", models.IntegerField()),
                ("diff_id", models.IntegerField()),
                ("error_breakdown", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        blank=True,
                        choices=[("ACTIVE", "Active"), ("ARCHIVED", "Archived")],
                        default="ACTIVE",
                        max_length=12,
                    ),
                ),
                (
                    "group",
                    models.CharField(
                        choices=[("GENERAL", "General"), ("LINT", "Lint")],
                        max_length=12,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Repo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255, unique=True)),
                ("default_branch", models.CharField(default="main", max_length=255)),
                ("url", models.CharField(max_length=255)),
                ("push_path", models.CharField(max_length=255)),
                ("pull_path", models.CharField(max_length=255)),
                ("is_initialized", models.BooleanField(default=False)),
                (
                    "system_path",
                    models.FilePathField(
                        allow_folders=True,
                        blank=True,
                        default="",
                        max_length=255,
                        path="/mediafiles/repos",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Revision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "revision_id",
                    models.IntegerField(blank=True, null=True, unique=True),
                ),
                ("diff_id", models.IntegerField(blank=True, null=True)),
                ("patch", models.TextField(blank=True, default="")),
                ("patch_data", models.JSONField(blank=True, default=dict)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("commit_id", models.CharField(blank=True, max_length=40, null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="LandingJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("SUBMITTED", "Submitted"),
                            ("IN_PROGRESS", "In progress"),
                            ("DEFERRED", "Deferred"),
                            ("FAILED", "Failed"),
                            ("LANDED", "Landed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        default=None,
                        max_length=32,
                        null=True,
                    ),
                ),
                (
                    "revision_to_diff_id",
                    models.JSONField(blank=True, default=dict, null=True),
                ),
                (
                    "revision_order",
                    models.JSONField(blank=True, default=dict, null=True),
                ),
                ("error", models.TextField(blank=True, default="")),
                (
                    "error_breakdown",
                    models.JSONField(blank=True, default=dict, null=True),
                ),
                (
                    "requester_email",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("landed_commit_id", models.TextField(blank=True, default="")),
                ("attempts", models.IntegerField(default=0)),
                ("priority", models.IntegerField(default=0)),
                ("duration_seconds", models.IntegerField(default=0)),
                (
                    "formatted_replacements",
                    models.JSONField(blank=True, default=None, null=True),
                ),
                ("target_commit_hash", models.TextField(blank=True, default="")),
                ("repository_name", models.TextField(blank=True, default="")),
                ("repository_url", models.TextField(blank=True, default="")),
                (
                    "target_repo",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="main.repo",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="RevisionLandingJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("index", models.IntegerField(blank=True, null=True)),
                ("diff_id", models.IntegerField(blank=True, null=True)),
                (
                    "landing_job",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="main.landingjob",
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="main.revision",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="landingjob",
            name="unsorted_revisions",
            field=models.ManyToManyField(
                through="main.RevisionLandingJob", to="main.revision"
            ),
        ),
        migrations.CreateModel(
            name="Worker",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255, unique=True)),
                ("is_paused", models.BooleanField(default=False)),
                ("is_stopped", models.BooleanField(default=False)),
                ("ssh_private_key", models.TextField(blank=True, null=True)),
                ("throttle_seconds", models.IntegerField(default=10)),
                ("sleep_seconds", models.IntegerField(default=10)),
                ("applicable_repos", models.ManyToManyField(to="main.repo")),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
