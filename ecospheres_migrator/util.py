from lxml import etree


XML_FORMAT = {
    'encoding': 'utf-8',
    'pretty_print': True,
    'xml_declaration': True
}


def xml_to_string(tree: etree._ElementTree, format: dict = XML_FORMAT):
    return etree.tostring(tree, **format)
