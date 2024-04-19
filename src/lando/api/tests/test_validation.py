# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest
from lando.main.support import ProblemException

from lando.api.legacy.validation import revision_id_to_int


def test_convertion_success():
    assert revision_id_to_int("D123") == 123


@pytest.mark.parametrize("id", ["123D", "123", "DAB", "A123"])
def test_convertion_failure_string(id):
    with pytest.raises(ProblemException):
        revision_id_to_int(id)


def test_convertion_failure_integer():
    with pytest.raises(TypeError):
        revision_id_to_int(123)
