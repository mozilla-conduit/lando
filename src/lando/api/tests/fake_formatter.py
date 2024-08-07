"""Fake formatter that rewrites text to mOcKiNg cAse"""

import sys


def split_chars(string) -> list:
    return list(string)


if __name__ == "__main__":
    stdin_content = sys.stdin.read()
    stdout_content = []

    for i, word in enumerate(split_chars(stdin_content)):
        stdout_content.append(word.upper() if i % 2 == 0 else word.lower())

    sys.stdout.write("".join(stdout_content))
    sys.exit(0)
