import os

import pytest
from xdist.plugin import pytest_xdist_auto_num_workers as default_pytest_xdist_auto_num_workers

# pytest_plugins needs to be defined in the root conftest.py.
pytest_plugins = [
    "lando.utils.github.tests.conftest",
]

def pytest_xdist_auto_num_workers(config: pytest.Config) -> int | None:
    """Limit the number of cores to use when running xdist tests.

    This is only used when `-n auto` or `-n logical` is passed to pytest.
    """
    keep_free_cores = 4

    if os.getenv("CI", False) == "1":
        # Fallback to built-in methods.
        return None

    if cpu_count := default_pytest_xdist_auto_num_workers(config):
        return max(1, cpu_count - keep_free_cores)

    return None
