from configparser import ConfigParser


def read_lando_config(lando_ini_contents: str) -> ConfigParser:
    """Attempt to read the `.lando.ini` file."""
    # ConfigParser will use `:` as a delimeter unless told otherwise.
    # We set our keys as `formatter:pattern` so specify `=` as the delimiters.
    parser = ConfigParser(delimiters="=")
    parser.read_string(lando_ini_contents)

    return parser
