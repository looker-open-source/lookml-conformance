"""Check that every quoted citation still appears, word for word, on the page it links to."""

from __future__ import annotations

import html
import re
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag

from lookml_conformance.cases import Case

Fetcher = Callable[[str], str]

USER_AGENT = "lookml-conformance citation checker (+https://github.com/josephaxisa/lookml-conformance)"
_BLOCK_TAGS = frozenset({
    "p", "div", "li", "ul", "ol", "br", "tr", "td", "th", "table", "pre", "section", "article", "aside",
    "blockquote", "dt", "dd", "header", "footer", "nav", "h1", "h2", "h3", "h4", "h5", "h6",
})  # fmt: skip
_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template"})
_PUNCTUATION = str.maketrans(
    {
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{NO-BREAK SPACE}": " ",
    }
)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class CitationProblem:
    case_id: str
    url: str
    quote: str
    reason: str


def normalize(text: str) -> str:
    """Make page text and quotes comparable: unescape entities, straighten quotes, collapse whitespace."""
    return _WHITESPACE.sub(" ", html.unescape(text).translate(_PUNCTUATION)).strip()


def page_text(document: str) -> str:
    """The visible text of an HTML page. Inline markup such as ``<code>`` does not add spaces."""
    parser = _TextExtractor()
    parser.feed(document)
    parser.close()
    return normalize("".join(parser.parts))


def fetch_url(url: str, timeout: float = 30.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return str(response.read().decode(charset, errors="replace"))


def check_citations(cases: Iterable[Case], fetch: Fetcher | None = None) -> list[CitationProblem]:
    """Fetch each cited page once and report every quote that is not on it."""
    fetch = fetch or fetch_url
    pages: dict[str, str | Exception] = {}
    problems = []
    for case in cases:
        for citation in case.citations:
            page = urldefrag(citation.url).url
            if page not in pages:
                try:
                    pages[page] = page_text(fetch(page))
                except Exception as exc:
                    pages[page] = exc  # reported for each citation of the page, not raised
            text = pages[page]
            if isinstance(text, Exception):
                reason = f"cannot fetch: {text}"
            elif normalize(citation.quote) not in text:
                reason = "quote not found on the page"
            else:
                continue
            problems.append(CitationProblem(case.id, citation.url, citation.quote, reason))
    return problems


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)
