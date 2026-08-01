from __future__ import annotations

import json
import re
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

from vav.common.exceptions import VavError

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/plain",
    "text/html",
    "application/json",
}
EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True)
class ParseResult:
    normalized_text: str
    blocks: list[dict[str, Any]]
    parser_name: str
    page_count: int | None
    quality_bps: int
    warnings: list[dict[str, object]]


def normalize_fragment(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.replace("\r\n", "\n").replace("\r", "\n"))
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def detect_mime_type(payload: bytes) -> str:
    if payload.startswith(b"%PDF-"):
        return "application/pdf"
    if payload.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                names = set(archive.namelist())
            if "word/document.xml" in names and "[Content_Types].xml" in names:
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except zipfile.BadZipFile:
            pass
    try:
        sample = payload[:8192].decode("utf-8").lstrip().casefold()
    except UnicodeDecodeError as error:
        raise VavError(
            "KNOWLEDGE_MIME_UNSUPPORTED",
            "The uploaded file is not a supported document format.",
            status_code=415,
        ) from error
    if sample.startswith("<!doctype html") or sample.startswith("<html"):
        return "text/html"
    return "text/plain"


def validate_upload(payload: bytes, declared_mime_type: str) -> str:
    if declared_mime_type not in SUPPORTED_MIME_TYPES:
        raise VavError("KNOWLEDGE_MIME_UNSUPPORTED", "File type is not supported.", status_code=415)
    if EICAR_MARKER in payload:
        raise VavError(
            "KNOWLEDGE_MALWARE_DETECTED",
            "The document failed the malware scan.",
            status_code=422,
        )
    detected = detect_mime_type(payload)
    compatible_text = (
        declared_mime_type
        in {
            "text/plain",
            "text/markdown",
            "application/json",
        }
        and detected == "text/plain"
    )
    if detected != declared_mime_type and not compatible_text:
        raise VavError(
            "KNOWLEDGE_MIME_MISMATCH",
            "Declared and detected document types do not match.",
            status_code=422,
        )
    return declared_mime_type


class _StructuredHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, int | None, str]] = []
        self._tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote"}:
            self._flush()
            self._tag = tag

    def handle_data(self, data: str) -> None:
        if self._tag:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._tag:
            self._flush()

    def _flush(self) -> None:
        if not self._tag:
            return
        value = normalize_fragment("".join(self._parts))
        if value:
            if self._tag.startswith("h"):
                kind, level = "heading", int(self._tag[1])
            elif self._tag == "li":
                kind, level = "list_item", None
            elif self._tag == "blockquote":
                kind, level = "quote", None
            else:
                kind, level = "paragraph", None
            self.blocks.append((kind, level, value))
        self._tag, self._parts = None, []


def _block(
    index: int,
    kind: str,
    text: str,
    *,
    heading_level: int | None = None,
    page_number: int | None = None,
    section_path: list[str] | None = None,
    source_locator: dict[str, object] | None = None,
) -> dict[str, Any]:
    return {
        "block_id": f"block-{index}",
        "block_type": kind,
        "text": normalize_fragment(text),
        "heading_level": heading_level,
        "page_number": page_number,
        "section_path": section_path or [],
        "source_locator": source_locator or {},
        "parent_block_id": None,
    }


def _parse_markdown_or_text(value: str, *, markdown: bool) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    sections: list[str] = []
    offset = 0
    for raw in re.split(r"\n\s*\n", value):
        text_value = normalize_fragment(raw)
        if not text_value:
            offset += len(raw) + 2
            continue
        kind, heading_level = "paragraph", None
        if markdown:
            heading = re.match(r"^(#{1,6})\s+(.+)$", text_value)
            if heading:
                heading_level = len(heading.group(1))
                text_value = heading.group(2).strip()
                sections = sections[: heading_level - 1] + [text_value]
                kind = "heading"
            elif all(line.lstrip().startswith(("- ", "* ", "+ ")) for line in raw.splitlines()):
                kind = "list_item"
            elif text_value.startswith(">"):
                kind, text_value = "quote", text_value.lstrip("> ")
            elif "|" in text_value and "---" in text_value:
                kind = "table"
        blocks.append(
            _block(
                len(blocks) + 1,
                kind,
                text_value,
                heading_level=heading_level,
                section_path=list(sections),
                source_locator={"start_offset": offset, "end_offset": offset + len(raw)},
            )
        )
        offset += len(raw) + 2
    return blocks


def _parse_docx(payload: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    blocks: list[dict[str, Any]] = []
    sections: list[str] = []
    body = root.find(f"{WORD_NS}body")
    if body is None:
        return blocks
    for element in body:
        if element.tag == f"{WORD_NS}p":
            value = normalize_fragment(
                "".join(node.text or "" for node in element.iter(f"{WORD_NS}t"))
            )
            if not value:
                continue
            style_node = element.find(f"{WORD_NS}pPr/{WORD_NS}pStyle")
            style = style_node.get(f"{WORD_NS}val", "") if style_node is not None else ""
            heading_match = re.match(r"Heading(\d+)", style, re.IGNORECASE)
            level = int(heading_match.group(1)) if heading_match else None
            kind = "heading" if level else "paragraph"
            if level:
                sections = sections[: level - 1] + [value]
            blocks.append(
                _block(
                    len(blocks) + 1,
                    kind,
                    value,
                    heading_level=level,
                    section_path=list(sections),
                    source_locator={"xml_element": len(blocks) + 1},
                )
            )
        elif element.tag == f"{WORD_NS}tbl":
            rows = []
            for row in element.findall(f".//{WORD_NS}tr"):
                cells = [
                    normalize_fragment(
                        "".join(node.text or "" for node in cell.iter(f"{WORD_NS}t"))
                    )
                    for cell in row.findall(f"{WORD_NS}tc")
                ]
                rows.append(" | ".join(cells))
            value = "\n".join(rows)
            if value:
                blocks.append(
                    _block(
                        len(blocks) + 1,
                        "table",
                        value,
                        section_path=list(sections),
                        source_locator={"xml_element": len(blocks) + 1},
                    )
                )
    return blocks


def _decode_pdf_literal(value: bytes) -> str:
    value = re.sub(
        rb"\\([0-7]{1,3})",
        lambda match: bytes([int(match.group(1), 8)]),
        value,
    )
    replacements = {
        b"\\n": b"\n",
        b"\\r": b"\r",
        b"\\t": b"\t",
        b"\\(": b"(",
        b"\\)": b")",
        b"\\\\": b"\\",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    for encoding in ("utf-8", "utf-16-be", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _pdf_text_streams(payload: bytes) -> list[str]:
    extracted: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", payload, re.DOTALL):
        stream = match.group(1)
        dictionary = payload[max(0, match.start() - 400) : match.start()]
        if b"/FlateDecode" in dictionary:
            try:
                stream = zlib.decompress(stream)
            except zlib.error:
                continue
        parts: list[str] = []
        for text_object in re.findall(rb"BT(.*?)ET", stream, re.DOTALL):
            for literal in re.findall(rb"\((?:\\.|[^\\)])*\)", text_object, re.DOTALL):
                value = normalize_fragment(_decode_pdf_literal(literal[1:-1]))
                if value:
                    parts.append(value)
            for hexadecimal in re.findall(rb"<([0-9A-Fa-f]{4,})>", text_object):
                try:
                    raw = bytes.fromhex(hexadecimal.decode())
                    encoding = "utf-16-be" if raw.startswith(b"\xfe\xff") else "utf-8"
                    value = normalize_fragment(raw.lstrip(b"\xfe\xff").decode(encoding))
                except (UnicodeDecodeError, ValueError):
                    continue
                if value:
                    parts.append(value)
        if parts:
            extracted.append(" ".join(parts))
    return extracted


def parse_document(payload: bytes, mime_type: str) -> ParseResult:
    validate_upload(payload, mime_type)
    page_count: int | None = None
    warnings: list[dict[str, object]] = []
    blocks: list[dict[str, Any]]
    if mime_type == "application/pdf":
        page_count = len(re.findall(rb"/Type\s*/Page\b", payload)) or None
        blocks = []
        for page_number, value in enumerate(_pdf_text_streams(payload), 1):
            blocks.append(
                _block(
                    len(blocks) + 1,
                    "paragraph",
                    value,
                    page_number=page_number,
                    source_locator={"page": page_number},
                )
            )
        if not blocks:
            warnings.append({"code": "PDF_TEXT_LAYER_UNAVAILABLE", "requires_ocr": True})
        parser_name = "pdf-text-layer-v1"
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        blocks = _parse_docx(payload)
        parser_name = "docx-xml"
    else:
        value = payload.decode("utf-8")
        if mime_type == "text/html":
            parser = _StructuredHTMLParser()
            parser.feed(value)
            parser.close()
            blocks = [
                _block(index, kind, text_value, heading_level=level)
                for index, (kind, level, text_value) in enumerate(parser.blocks, 1)
            ]
            parser_name = "html5-stdlib"
        elif mime_type == "application/json":
            decoded = json.loads(value)
            rendered = json.dumps(decoded, ensure_ascii=False, indent=2)
            blocks = _parse_markdown_or_text(rendered, markdown=False)
            parser_name = "json-stdlib"
        else:
            blocks = _parse_markdown_or_text(value, markdown=mime_type == "text/markdown")
            parser_name = "markdown-structural" if mime_type == "text/markdown" else "plain-text"
    normalized = "\n".join(block["text"] for block in blocks if block.get("text"))
    character_count = len(normalized)
    quality = 10000
    if not blocks or character_count < 20:
        quality = 3000
        warnings.append({"code": "INSUFFICIENT_EXTRACTED_TEXT"})
    elif character_count < 100:
        quality = 7500
        warnings.append({"code": "SHORT_DOCUMENT_REVIEW"})
    return ParseResult(normalized, blocks, parser_name, page_count, quality, warnings)
