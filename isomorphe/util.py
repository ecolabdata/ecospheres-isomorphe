from cmarkgfm import github_flavored_markdown_to_html
from cmarkgfm.cmark import Options as cmark_options
from lxml import etree

XML_FORMAT = {"encoding": "utf-8", "pretty_print": True, "xml_declaration": True}


def xml_to_string(tree: etree._ElementTree, format: dict = XML_FORMAT):
    etree.indent(tree, space=" ")
    return etree.tostring(tree, **format)


def render_markdown(content: str):
    return github_flavored_markdown_to_html(content, options=cmark_options.CMARK_OPT_UNSAFE)
