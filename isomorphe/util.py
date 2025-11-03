from typing import Any

from cmarkgfm import github_flavored_markdown_to_html
from cmarkgfm.cmark import Options as cmark_options
from lxml import etree

XML_FORMAT = {"encoding": "utf-8", "pretty_print": True, "xml_declaration": True}


def xml_to_bytes(tree: etree._ElementTree, format: dict[str, Any] = XML_FORMAT) -> bytes:
    etree.indent(tree, space=" ")
    return etree.tostring(tree, **format)


def bytes_to_xml(content: bytes) -> etree._ElementTree:
    return etree.fromstring(content, parser=None)


def render_markdown(text: str):
    return github_flavored_markdown_to_html(text, options=cmark_options.CMARK_OPT_UNSAFE)
