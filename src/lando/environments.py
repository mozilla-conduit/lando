from enum import StrEnum, auto


class Environment(StrEnum):
    test = auto()
    local = auto()
    development = auto()
    staging = auto()
    production = auto()

    @property
    def is_test(self) -> bool:
        return self == self.test

    @property
    def is_lower(self) -> bool:
        return self != self.production

    @property
    def is_remote(self) -> bool:
        return self in (self.development, self.staging, self.production)
