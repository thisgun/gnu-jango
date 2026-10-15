import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class ParsedParagraph:
    text: str
    section: str
    anchor: str
    is_heading: bool = False


def slugify_heading(text, index):
    """Match handbook/page-toc.tsx slugifyHeading(), including its UTF-16 slice length."""
    lowered = str(text or "").strip().lower()
    base = "".join(
        char
        for char in lowered
        if unicodedata.category(char).startswith(("L", "N")) or char.isspace() or char == "-"
    )
    base = re.sub(r"\s+", "-", base) or "section"
    # JavaScript String.slice(0, 60) counts UTF-16 code units, not Unicode code points.
    base = base.encode("utf-16-le")[:120].decode("utf-16-le", errors="ignore")
    return f"{base or 'section'}-{index}"


class _ManualHtmlParser(HTMLParser):
    _BLOCKS = {"address", "article", "blockquote", "div", "li", "p", "pre", "section", "tr"}
    _IGNORED = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._buffer = []
        self._mode = "paragraph"
        self._heading_tag = None
        self._ignored = []
        self._section = ""
        self._anchor = ""
        self._heading_index = 0

    @staticmethod
    def _normalise(text):
        return " ".join(text.split())

    def _flush_paragraph(self):
        if self._mode == "heading":
            return
        text = self._normalise("".join(self._buffer))
        self._buffer = []
        if text:
            self.blocks.append(ParsedParagraph(text, self._section, self._anchor))

    def _finish_heading(self):
        text = self._normalise("".join(self._buffer))
        self._buffer = []
        self._mode = "paragraph"
        self._heading_tag = None
        if not text:
            return
        anchor = slugify_heading(text, self._heading_index)
        self._heading_index += 1
        self._section = text
        self._anchor = anchor
        self.blocks.append(ParsedParagraph(text, text, anchor, is_heading=True))

    def handle_starttag(self, tag, attrs):
        if self._ignored:
            if tag in self._IGNORED:
                self._ignored.append(tag)
            return
        if tag in self._IGNORED:
            self._flush_paragraph()
            self._ignored.append(tag)
            return
        if tag in {"h2", "h3"}:
            self._flush_paragraph()
            self._buffer = []
            self._mode = "heading"
            self._heading_tag = tag
        elif tag == "br":
            self._flush_paragraph()
        elif tag in self._BLOCKS:
            self._flush_paragraph()

    def handle_endtag(self, tag):
        if self._ignored:
            if tag in self._ignored:
                self._ignored.pop()
            return
        if tag in {"h2", "h3"} and self._mode == "heading" and tag == self._heading_tag:
            self._finish_heading()
        elif tag in self._BLOCKS:
            self._flush_paragraph()

    def handle_data(self, data):
        if not self._ignored:
            self._buffer.append(data)

    def close(self):
        super().close()
        if self._mode == "heading":
            self._finish_heading()
        else:
            self._flush_paragraph()


def parse_manual_html(value):
    """Extract safe text blocks and h2/h3 anchors without rendering or regex-stripping HTML."""
    parser = _ManualHtmlParser()
    parser.feed(str(value or ""))
    parser.close()
    return parser.blocks
