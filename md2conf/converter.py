import re
from urllib.parse import urlparse
from typing import List, Optional

import lxml.etree as ET
import markdown

ET.register_namespace("ac", "http://atlassian.com/content")
ET.register_namespace("ri", "http://atlassian.com/resource/identifier")


class ParseError(RuntimeError):
    pass


def is_absolute_url(url):
    return bool(urlparse(url).netloc)


def markdown_to_html(content: str) -> str:
    return markdown.markdown(
        content,
        extensions=[
            "markdown.extensions.tables",
            "markdown.extensions.fenced_code",
            "pymdownx.tilde",
            "sane_lists",
        ],
    )


def element_from_string(text: str) -> ET.Element:
    "Creates an XML node from its string representation."

    return element_from_string_list([text])


def element_from_string_list(items: List[str]) -> ET.Element:
    "Creates an XML node from its string representation."

    parser = ET.XMLParser(remove_blank_text=True, strip_cdata=False)

    data = [
        '<?xml version="1.0"?>',
        '<root xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource/identifier">',
    ]
    data.extend(items)
    data.append("</root>")

    try:
        root = ET.fromstringlist(data, parser=parser)
        if len(root) > 1:
            return root
        else:
            return root[0]
    except ET.XMLSyntaxError as e:
        raise ParseError(e)


_languages = [
    "actionscript3",
    "bash",
    "csharp",
    "coldfusion",
    "cpp",
    "css",
    "delphi",
    "diff",
    "erlang",
    "groovy",
    "html",
    "java",
    "javafx",
    "javascript",
    "json",
    "perl",
    "php",
    "powershell",
    "python",
    "ruby",
    "scala",
    "sql",
    "vb",
    "xml",
]


class NodeVisitor:
    def visit(self, node: ET.Element) -> None:
        if len(node) < 1:
            return

        for index in range(len(node)):
            source = node[index]
            target = self.transform(source)
            if target is not None:
                node[index] = target
            else:
                self.visit(source)

    def transform(self, child: ET.Element) -> Optional[ET.Element]:
        pass


class ConfluenceStorageFormatConverter(NodeVisitor):
    "Transforms a plain HTML tree into the Confluence storage format."

    links: List[str]
    images: List[str]

    def __init__(self) -> None:
        super().__init__()
        self.links = []
        self.images = []

    def _transform_link(self, anchor: ET.Element) -> ET.Element:
        url = anchor.attrib["href"]
        if not is_absolute_url(url):
            self.links.append(url)

    def _transform_image(self, image: ET.Element) -> ET.Element:
        path = image.attrib["src"]
        self.images.append(path)
        caption = image.attrib["alt"]
        return element_from_string_list(
            [
                '<ac:image ac:align="center" ac:layout="center">',
                f'<ri:attachment ri:filename="{path}" />',
                f"<ac:caption><p>{caption}</p></ac:caption>",
                "</ac:image>",
            ]
        )

    def _transform_block(self, code: ET.Element) -> ET.Element:
        language = code.attrib.get("class")
        if language:
            language = re.match("^language-(.*)$", language).group(1)
        if language not in _languages:
            language = "none"
        content = code.text
        return element_from_string_list(
            [
                '<ac:structured-macro ac:name="code" ac:schema-version="1">',
                '<ac:parameter ac:name="theme">Midnight</ac:parameter>',
                f'<ac:parameter ac:name="language">{language}</ac:parameter>',
                '<ac:parameter ac:name="linenumbers">true</ac:parameter>',
                f"<ac:plain-text-body><![CDATA[{content}]]></ac:plain-text-body>",
                "</ac:structured-macro>",
            ]
        )

    def transform(self, child: ET.Element) -> Optional[ET.Element]:
        # <p><img src="..." /></p>
        if child.tag == "p" and len(child) == 1 and child[0].tag == "img":
            return self._transform_image(child[0])

        # <img src="..." alt="..." />
        elif child.tag == "img":
            return self._transform_image(child)

        # <a href="..."> ... </a>
        elif child.tag == "a":
            return self._transform_link(child)

        # <pre><code class="language-java"> ... </code></pre>
        elif child.tag == "pre" and len(child) == 1 and child[0].tag == "code":
            return self._transform_block(child[0])


class ConfluenceStorageFormatCleaner(NodeVisitor):
    "Removes volatile attributes from a Confluence storage format XHTML document."

    def transform(self, child: ET.Element) -> Optional[ET.Element]:
        child.attrib.pop("{http://atlassian.com/content}macro-id", None)
        child.attrib.pop(
            "{http://atlassian.com/resource/identifier}version-at-save", None
        )


class ConfluenceDocument:
    id: str
    links: List[str]
    images: List[str]

    root: ET.Element

    def __init__(self, html: str) -> None:
        match = re.search(r"<!--\s+confluence-page-id:\s*(\d+)\s+-->", html)
        self.id = match.group(1)

        self.root = element_from_string_list(
            [
                '<ac:structured-macro ac:name="info" ac:schema-version="1">',
                "<ac:rich-text-body><p>This page has been generated with a tool.</p></ac:rich-text-body>",
                "</ac:structured-macro>",
                html[: match.start()],
                html[match.end() :],
            ]
        )

        converter = ConfluenceStorageFormatConverter()
        converter.visit(self.root)
        self.links = converter.links
        self.images = converter.images

    def xhtml(self) -> str:
        return _content_to_string(self.root)


def sanitize_confluence(html: str) -> str:
    "Generates a sanitized version of a Confluence storage format XHTML document with no volatile attributes."

    root = element_from_string(html)
    ConfluenceStorageFormatCleaner().visit(root)
    return _content_to_string(root)


def _content_to_string(root: ET.Element) -> str:
    xml = ET.tostring(root, encoding="utf8", method="xml").decode("utf8")
    m = re.match(r"^<root\s+[^>]*>(.*)</root>\s*$", xml, re.DOTALL)
    return m.group(1)