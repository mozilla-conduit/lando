import os

import pytest

# pytest_plugins needs to be defined in the root conftest.py.
pytest_plugins = [
    "lando.utils.github.tests.conftest",
]

def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """ Limit the number of cores to use when running xdist tests.

    This is only used when `-n auto` or `-n logical` is passed to pytest.
    """
    keep_free_cores = 4
    cpu_count = os.cpu_count() or 1
    return max(1, cpu_count - keep_free_cores)
