import re
from pathlib import Path
from typing import Any

from saxonche import PySaxonProcessor, PyXdmNode

SAXON_PROC = PySaxonProcessor(license=False)
SAXON_PROC.set_configuration_property("http://saxon.sf.net/feature/strip-whitespace", "all")


def xml_to_string(tree: PyXdmNode) -> str:
    xquery_proc = SAXON_PROC.new_xquery_processor()
    xquery_proc.set_property("!omit-xml-declaration", "no")
    xquery_proc.set_property("!indent", "yes")
    xquery_proc.set_context(xdm_item=tree)
    content = xquery_proc.run_query_to_string(query_text=".")
    return content


def string_to_xml(content: str) -> PyXdmNode:
    return SAXON_PROC.parse_xml(xml_text=content)


def path_to_xml(path: Path | str) -> PyXdmNode:
    return SAXON_PROC.parse_xml(xml_file_name=str(path))


def get_namespaces(tree: PyXdmNode) -> dict[str, str]:
    # Saxon API doesn't provide a way to list the namespaces, so we use XPath.
    xpath_proc = SAXON_PROC.new_xpath_processor()
    xpath_proc.set_context(xdm_item=tree)
    # Operate on concatenated "prefix|uri" strings because distinct-values() is picky.
    matches = xpath_proc.evaluate(
        "distinct-values(//namespace::* ! concat(name(.), '|', string(.)))"
    )
    namespaces = dict([ns.string_value.split("|") for ns in matches])
    return namespaces


def xpath_eval(tree: PyXdmNode, xpath: str) -> list[PyXdmNode]:
    xpath_proc = SAXON_PROC.new_xpath_processor()
    for ns_prefix, ns_uri in get_namespaces(tree).items():
        xpath_proc.declare_namespace(ns_prefix, ns_uri)
    xpath_proc.set_context(xdm_item=tree)
    matches = xpath_proc.evaluate(xpath) or []
    return matches


def xslt_apply(
    tree: PyXdmNode, stylesheet: PyXdmNode, params: dict[str, Any] | None = None
) -> tuple[PyXdmNode, list[str]]:
    xslt_proc = SAXON_PROC.new_xslt30_processor()
    xslt_exec = xslt_proc.compile_stylesheet(stylesheet_node=stylesheet)
    xslt_exec.set_save_xsl_message(True)
    if params:
        for param_name, param_value in params.items():
            if v := param_value.strip():
                xslt_exec.set_parameter(param_name, SAXON_PROC.make_string_value(v))
    transformed = xslt_exec.transform_to_value(xdm_node=tree).head
    messages = [node.string_value for node in (xslt_exec.get_xsl_messages() or [])]
    return transformed, messages


def format_xml(content: str) -> str:
    return xml_to_string(string_to_xml(content))


def xml_encoding(binary_content: bytes) -> str | None:
    if m := re.match(rb"""<\?xml[^>]+?encoding=['"](.+?)['"]""", binary_content):
        return m[1].decode()
