import json
import os.path

import pytest

from lando.api.legacy.phabricator_patch import patch_to_changes


@pytest.mark.parametrize("patch_name", ["basic", "random", "add"])
def test_patch_to_changes(patch_directory, patch_name):
    """Test the method to convert a raw patch into a list of Phabricator changes"""

    patch_path = os.path.join(patch_directory, f"{patch_name}.diff")
    result_path = os.path.join(patch_directory, f"{patch_name}.json")
    with open(patch_path) as p:
        output = patch_to_changes(p.read(), "deadbeef123")

    assert output == json.load(open(result_path))
