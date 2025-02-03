# Generated by Django 5.1.4 on 2025-01-28 07:04

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("main", "0013_alter_repo_scm_type_alter_worker_scm"),
        ("main", "0013_alter_repo_scm_type_alter_worker_scm"),
        ("main", "0013_alter_repo_scm_type_alter_worker_scm"),
    ]

    operations = [
        migrations.CreateModel(
            name="File",
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
                ("name", models.CharField(max_length=4096)),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING, to="main.repo"
                    ),
                ),
            ],
            options={
                "unique_together": {("repo", "name")},
            },
        ),
        migrations.CreateModel(
            name="Commit",
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
                (
                    "hash",
                    models.CharField(
                        db_index=True,
                        max_length=160,
                        validators=[
                            django.core.validators.MaxLengthValidator(160),
                            django.core.validators.MinLengthValidator(160),
                            django.core.validators.RegexValidator("^([a-fA-F0-9])+"),
                        ],
                    ),
                ),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING, to="main.repo"
                    ),
                ),
                ("author", models.CharField(db_index=True, max_length=512)),
                ("desc", models.TextField()),
                (
                    "parents",
                    models.ManyToManyField(
                        blank=True, related_name="descendents", to="pushlog.commit"
                    ),
                ),
                ("files", models.ManyToManyField(to="pushlog.file")),
                ("date", models.DateField(db_index=True)),
            ],
            options={
                "unique_together": {("repo", "hash")},
            },
        ),
        migrations.CreateModel(
            name="Tag",
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
                ("name", models.CharField(max_length=255)),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING, to="main.repo"
                    ),
                ),
                (
                    "commit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="pushlog.commit"
                    ),
                ),
            ],
            options={
                "unique_together": {("repo", "name")},
            },
        ),
        migrations.CreateModel(
            name="Push",
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
                ("push_id", models.PositiveIntegerField()),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING, to="main.repo"
                    ),
                ),
                ("date", models.DateField(auto_now_add=True, db_index=True)),
                ("user", models.EmailField(max_length=320)),
                ("commits", models.ManyToManyField(to="pushlog.commit")),
                ("branch", models.CharField(max_length=255)),
            ],
            options={
                "unique_together": {("push_id", "repo")},
            },
        ),
    ]
