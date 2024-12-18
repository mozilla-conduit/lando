from enum import StrEnum, auto


class Environment(StrEnum):
    """Specify which environment Lando is running on, to be used in settings."""

    # "test" refers to the environment that automated tests run in.
    test = auto()

    # "local" refers to the local development environment.
    local = auto()

    # "development" and "staging" refer to lower environments (remote).
    development = auto()
    staging = auto()

    # "production" refers to the remote production environment.
    production = auto()

    @property
    def is_test(self) -> bool:
        """Return True if this is the test environment."""
        return self == self.test

    @property
    def is_lower(self) -> bool:
        """Returns True if this is a lower environment."""
        return self != self.production

    @property
    def is_production(self) -> bool:
        """Returns True if this is a production environment."""
        return self == self.production

    @property
    def is_remote(self) -> bool:
        """Returns True if this is a remote environment."""
        return self in (self.development, self.staging, self.production)
