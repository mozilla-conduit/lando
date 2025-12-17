import pytest

from lando.api.legacy.validation import parse_revision_ids, revision_id_to_int
from lando.main.support import LegacyAPIException


def test_convertion_success():
    assert revision_id_to_int("D123") == 123


@pytest.mark.parametrize("id", ["123D", "123", "DAB", "A123"])
def test_convertion_failure_string(id):
    with pytest.raises(LegacyAPIException):
        revision_id_to_int(id)


def test_convertion_failure_integer():
    with pytest.raises(TypeError):
        revision_id_to_int(123)


@pytest.mark.parametrize(
    "revision_ids_input,expected_output",
    [
        # Valid cases
        ("1234", [1234]),
        ("1234,5678", [1234, 5678]),
        ("1234, 5678, 9012", [1234, 5678, 9012]),
        ("  1234  ,  5678  ", [1234, 5678]),
        ("1234,5678,9012,3456", [1234, 5678, 9012, 3456]),
        # Edge cases with trailing/leading/double commas (should be filtered out)
        ("1234,", [1234]),
        (",1234", [1234]),
        ("1234,,5678", [1234, 5678]),
        ("  1234  ,  ,  5678  ", [1234, 5678]),
    ],
)
def test_parse_revision_ids_valid(revision_ids_input, expected_output):
    """Test parsing valid comma-separated revision IDs."""
    result = parse_revision_ids(revision_ids_input)
    assert result == expected_output


@pytest.mark.parametrize(
    "revision_ids_input,expected_error_msg",
    [
        # Empty or whitespace-only strings
        ("", "At least one revision ID is required."),
        ("   ", "At least one revision ID is required."),
        (",", "At least one revision ID is required."),
        (",,", "At least one revision ID is required."),
        # Invalid format (non-integers)
        ("abc", "Invalid revision IDs. Must be comma-separated integers."),
        ("1234,abc", "Invalid revision IDs. Must be comma-separated integers."),
        ("1234,abc,5678", "Invalid revision IDs. Must be comma-separated integers."),
        ("1.5", "Invalid revision IDs. Must be comma-separated integers."),
        ("1234,5.5,5678", "Invalid revision IDs. Must be comma-separated integers."),
    ],
)
def test_parse_revision_ids_invalid(revision_ids_input, expected_error_msg):
    """Test parsing invalid comma-separated revision IDs raises ValueError."""
    with pytest.raises(ValueError, match=expected_error_msg):
        parse_revision_ids(revision_ids_input)
