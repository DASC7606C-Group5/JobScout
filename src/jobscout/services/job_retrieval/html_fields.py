"""Small HTML tree for source field extraction; no browser or LLM required."""

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    children: list[Element | str] = field(default_factory=list)

    def text(self) -> str:
        if self.tag in {"script", "style"}:
            return ""
        return " ".join(c.text() if isinstance(c, Element) else c for c in self.children).strip()

    def find(self, *, tag: str = "", attr: str = "", value: str = "") -> list[Element]:
        matches: list[Element] = []
        if (not tag or self.tag == tag) and (
            not attr
            or (
                value in self.attrs.get(attr, "").split()
                if attr == "class"
                else self.attrs.get(attr) == value
            )
        ):
            matches.append(self)
        for child in self.children:
            if isinstance(child, Element):
                matches.extend(child.find(tag=tag, attr=attr, value=value))
        return matches

    def field(self, attr: str, value: str) -> str | None:
        nodes = self.find(attr=attr, value=value)
        return nodes[0].text() or None if nodes else None


class Tree(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("root", {})
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Element(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)
