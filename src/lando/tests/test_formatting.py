"""
Code Style Tests.
"""

import subprocess

from lando.settings import LINT_PATHS


def test_black():
    cmd = ("black", "--diff")
    output = subprocess.check_output(cmd + LINT_PATHS)
    assert not output, "The python code does not adhere to the project style."


def test_ruff():
    passed = []
    for lint_path in LINT_PATHS:
        passed.append(
            subprocess.call(("ruff", "check", lint_path, "--target-version", "py310")) == 0
        )
    assert all(passed), "ruff did not run cleanly."
