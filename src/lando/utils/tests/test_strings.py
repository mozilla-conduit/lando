import pytest

from lando.utils.strings import (
    LOG_OUTPUT_HEAD_LIMIT,
    LOG_OUTPUT_TAIL_LIMIT,
    truncate_text,
)


@pytest.mark.parametrize(
    "case_name,input_string",
    [
        ("empty", ""),
        ("short", "hello world"),
        (
            "just_under_boundary",
            "x" * (LOG_OUTPUT_HEAD_LIMIT + LOG_OUTPUT_TAIL_LIMIT - 1),
        ),
        ("at_boundary", "x" * (LOG_OUTPUT_HEAD_LIMIT + LOG_OUTPUT_TAIL_LIMIT)),
    ],
)
def test_truncate_text_passes_short_input_through(case_name, input_string):
    assert (
        truncate_text(input_string) == input_string
    ), f"`truncate_text` should leave `{case_name}` input unchanged."


@pytest.mark.parametrize("middle_size", [1, 1000, 100_000])
def test_truncate_text_long_keeps_head_and_tail(middle_size):
    head = "H" * LOG_OUTPUT_HEAD_LIMIT
    middle = "M" * middle_size
    tail = "T" * LOG_OUTPUT_TAIL_LIMIT
    long_output = head + middle + tail

    result = truncate_text(long_output)

    assert result.startswith(
        head
    ), "Truncated text should preserve the first `LOG_OUTPUT_HEAD_LIMIT` characters."
    assert result.endswith(
        tail
    ), "Truncated text should preserve the last `LOG_OUTPUT_TAIL_LIMIT` characters."
    assert (
        f"[{middle_size} bytes omitted]" in result
    ), "Truncated text should include a marker reporting the omitted byte count."
    assert (
        "M" not in result
    ), "Truncated text should not contain any of the omitted middle section."
