from cmarkgfm import github_flavored_markdown_to_html
from cmarkgfm.cmark import Options as cmark_options


def render_markdown(text: str):
    return github_flavored_markdown_to_html(text, options=cmark_options.CMARK_OPT_UNSAFE)
