from itertools import batched
from pathlib import Path

from saxonche import PySaxonProcessor, PyXdmNode

SAXON_PROC = PySaxonProcessor(license=False)
SAXON_PROC.set_configuration_property("http://saxon.sf.net/feature/strip-whitespace", "all")


def xml_to_string(tree: PyXdmNode) -> str:
    xquery_proc = SAXON_PROC.new_xquery_processor()
    xquery_proc.set_context(xdm_item=tree)
    xquery_proc.set_property("!omit-xml-declaration", "no")
    xquery_proc.set_property("!indent", "yes")
    return xquery_proc.run_query_to_string(query_text=".")


def string_to_xml(content: str) -> PyXdmNode:
    return SAXON_PROC.parse_xml(xml_text=content)


def path_to_xml(path: Path | str) -> PyXdmNode:
    return SAXON_PROC.parse_xml(xml_file_name=str(path))


def get_namespaces(tree: PyXdmNode) -> dict[str, str]:
    # Saxon API doesn't provide a way to list the namespaces, so we use XPath
    xpath_proc = SAXON_PROC.new_xpath_processor()
    xpath_proc.set_context(xdm_item=tree)
    # xpath generates a flat list of namespaces' prefix and uri: [pre1, uri1, pre2, uri2, ...]
    matches = xpath_proc.evaluate("distinct-values(//namespace::* ! (name(.), .))") or []
    return {ns[0].string_value: ns[1].string_value for ns in batched(matches, n=2)}


def get_xpath(tree: PyXdmNode, xpath: str) -> list[PyXdmNode]:
    xpath_proc = SAXON_PROC.new_xpath_processor()
    for k, v in get_namespaces(tree).items():
        xpath_proc.declare_namespace(k, v)
    xpath_proc.set_context(xdm_item=tree)
    matches = xpath_proc.evaluate(xpath) or []
    return matches
