# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os
import subprocess
import sys
from typing import Optional

import click

from lando.api.legacy.systems import Subsystem
from lando.main.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableTypeChoices,
)

LINT_PATHS = ("setup.py", "tasks.py", "landoapi", "migrations", "tests")


def get_subsystems(exclude: Optional[list[Subsystem]] = None) -> list[Subsystem]:
    """Get subsystems from the app, excluding those specified in the given parameter.

    Args:
        exclude (list of Subsystem): Subsystems to exclude.

    Returns: list of Subsystem
    """
    from lando.api.legacy.app import SUBSYSTEMS

    exclusions = exclude or []
    return [s for s in SUBSYSTEMS if s not in exclusions]


def create_lando_api_app():
    from lando.api.legacy.app import construct_app, load_config

    config = load_config()
    app = construct_app(config)
    for system in get_subsystems():
        system.init_app(app.app)

    return app.app


def cli():
    """Lando API cli."""


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("celery_arguments", nargs=-1, type=click.UNPROCESSED)
def worker(celery_arguments):
    """Initialize a Celery worker for this app."""
    from lando.api.legacy.app import repo_clone_subsystem

    for system in get_subsystems(exclude=[repo_clone_subsystem]):
        system.ensure_ready()

    from lando.api.legacy.celery import celery

    celery.worker_main((sys.argv[0],) + celery_arguments)


@cli.command(name="landing-worker")
def landing_worker():
    from lando.api.legacy.app import auth0_subsystem, lando_ui_subsystem

    exclusions = [auth0_subsystem, lando_ui_subsystem]
    for system in get_subsystems(exclude=exclusions):
        system.ensure_ready()

    from lando.api.legacy.workers.landing_worker import LandingWorker

    worker = LandingWorker()
    worker.start()


@cli.command(name="run-pre-deploy-sequence")
def run_pre_deploy_sequence():
    """Runs the sequence of commands required before a deployment."""
    ConfigurationVariable.set(
        ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "1"
    )
    ConfigurationVariable.set(
        ConfigurationKey.LANDING_WORKER_PAUSED, VariableTypeChoices.BOOL, "1"
    )


@cli.command(name="run-post-deploy-sequence")
def run_post_deploy_sequence():
    """Runs the sequence of commands required after a deployment."""
    ConfigurationVariable.set(
        ConfigurationKey.API_IN_MAINTENANCE, VariableTypeChoices.BOOL, "0"
    )
    ConfigurationVariable.set(
        ConfigurationKey.LANDING_WORKER_PAUSED, VariableTypeChoices.BOOL, "0"
    )


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("celery_arguments", nargs=-1, type=click.UNPROCESSED)
def celery(celery_arguments):
    """Run the celery base command for this app."""
    from lando.api.legacy.app import repo_clone_subsystem

    for system in get_subsystems(exclude=[repo_clone_subsystem]):
        system.ensure_ready()

    from lando.api.legacy.celery import celery

    celery.start([sys.argv[0]] + list(celery_arguments))


@cli.command()
def uwsgi():
    """Run the service in production mode with uwsgi."""
    from lando.api.legacy.app import repo_clone_subsystem

    for system in get_subsystems(exclude=[repo_clone_subsystem]):
        system.ensure_ready()

    logging.shutdown()
    os.execvp("uwsgi", ["uwsgi"])


@cli.command(name="format", with_appcontext=False)
@click.option("--in-place", "-i", is_flag=True)
def format_code(in_place):
    """Format python code"""
    cmd = ("black",)
    if not in_place:
        cmd = cmd + ("--diff",)
    os.execvp("black", cmd + LINT_PATHS)


@cli.command(with_appcontext=False)
def ruff():
    """Run ruff on lint paths."""
    for lint_path in LINT_PATHS:
        subprocess.call(
            ("ruff", "check", "--fix", "--target-version", "py39", lint_path)
        )


@cli.command(with_appcontext=False, context_settings={"ignore_unknown_options": True})
@click.argument("pytest_arguments", nargs=-1, type=click.UNPROCESSED)
def test(pytest_arguments):
    """Run the tests."""
    os.execvp("pytest", ("pytest",) + pytest_arguments)


if __name__ == "__main__":
    cli()
