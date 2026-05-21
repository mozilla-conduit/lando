"""
Code Style Tests.
"""

import subprocess

from lando.settings import LINT_PATHS, STATIC_LINT_PATHS


def test_ruff_format():
    cmd = ("ruff", "format", "--diff")
    output = subprocess.run(cmd + LINT_PATHS, stdout=subprocess.PIPE)
    assert not output.stdout, "The python code does not adhere to the project style."
    assert not output.returncode, f"{' '.join(cmd)} did not run successfully."


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


def test_prettier():
    cmd = ("prettier", "--check", *STATIC_LINT_PATHS)
    output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert output.returncode == 0, (
        f"The CSS/JS code does not adhere to the project style:\n"
        f"{output.stdout.decode()}{output.stderr.decode()}"
    )
