from django.db.migrations.loader import MigrationLoader
from django.test import override_settings


def test_no_migration_conflicts():
    """Each app's migration graph must have exactly one leaf node."""
    # `connection=None` skips the DB. `MIGRATION_MODULES={}` defeats
    # `pytest-django`'s `--no-migrations` patch, which would otherwise
    # hide every migration from the loader once `django_db_setup` runs.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        conflicts = loader.detect_conflicts()

    assert not conflicts, (
        "Conflicting migrations detected (multiple leaf nodes per app): "
        f"{conflicts}. Renumber/rebase the offending migration or run "
        "`makemigrations --merge`."
    )
