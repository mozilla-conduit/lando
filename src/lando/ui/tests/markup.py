"""Helpers for asserting on rendered HTML."""

from html.parser import HTMLParser


class ElementCollector(HTMLParser):
    """Collect every start tag and its attributes from rendered markup."""

    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.elements.append((tag, dict(attrs)))


def elements(html: str, tag: str, **attributes: str) -> list[dict]:
    """Return the attributes of every `tag` element carrying `attributes`."""
    collector = ElementCollector()
    collector.feed(html)
    return [
        attrs
        for element_tag, attrs in collector.elements
        if element_tag == tag
        and all(attrs.get(name) == value for name, value in attributes.items())
    ]


def squashed(html: str) -> str:
    """Return `html` with each run of whitespace collapsed to one space."""
    return " ".join(html.split())
