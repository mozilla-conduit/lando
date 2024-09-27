"""
Code Style Tests.
"""

import subprocess


def test_check_python_style():
    cmd = ("black", "--diff", ".")
    output = subprocess.check_output(cmd)
    assert not output


def test_check_python_flake8():
    files = (".",)
    cmd = ("flake8",)
    passed = subprocess.call(cmd + files) == 0
    assert passed, "Flake8 did not run cleanly."
