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
        passed.append(subprocess.call(("ruff", "check", lint_path)) == 0)
    assert all(passed), "ruff did not run cleanly."


def test_djlint():
    passed = []
    for lint_path in LINT_PATHS:
        passed.append(subprocess.call(("djlint", lint_path, "--check")) == 0)
    assert all(passed), "djlint did not run cleanly."
