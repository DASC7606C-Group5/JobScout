"""Extract visible source text from Lexbor HTML nodes."""

from selectolax.lexbor import LexborHTMLParser, LexborNode


def visible_text(html: str) -> str:
    tree = LexborHTMLParser(html)
    tree.strip_tags(["script", "style"])
    return tree.text(separator=" ", strip=True)


def field_text(node: LexborHTMLParser | LexborNode, selector: str) -> str | None:
    field = node.css_first(selector)
    return field.text(separator=" ", strip=True) or None if field is not None else None
