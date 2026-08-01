from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from vav.modules.knowledge.parsing import parse_document, validate_upload


def docx_fixture() -> bytes:
    document = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Healthy Boundaries</w:t></w:r></w:p>
    <w:p><w:r><w:t>Respect consent and personal limits.</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Rule</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Meaning</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  </w:body>
</w:document>"""
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def test_markdown_parser_preserves_heading_list_and_source_offsets() -> None:
    result = parse_document(b"# Boundaries\n\nRespect consent.\n\n- Pause\n- Ask", "text/markdown")
    assert [item["block_type"] for item in result.blocks] == [
        "heading",
        "paragraph",
        "list_item",
    ]
    assert result.blocks[1]["section_path"] == ["Boundaries"]
    assert result.blocks[1]["source_locator"]["start_offset"] > 0


def test_docx_parser_preserves_headings_paragraphs_and_tables() -> None:
    result = parse_document(
        docx_fixture(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert [item["block_type"] for item in result.blocks] == [
        "heading",
        "paragraph",
        "table",
    ]
    assert result.blocks[1]["section_path"] == ["Healthy Boundaries"]
    assert "Rule | Meaning" in result.blocks[2]["text"]


def test_html_parser_keeps_structure_without_script_content() -> None:
    result = parse_document(
        (
            b"<!doctype html><html><h1>Scope</h1>"
            b"<p>Public service description.</p><script>secret</script></html>"
        ),
        "text/html",
    )
    assert [item["block_type"] for item in result.blocks] == ["heading", "paragraph"]
    assert "secret" not in result.normalized_text


def test_pdf_text_layer_preserves_page_locator() -> None:
    payload = (
        b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n"
        b"2 0 obj<</Length 54>>stream\nBT /F1 12 Tf (Respect boundaries) Tj ET\n"
        b"endstream\nendobj\n%%EOF"
    )
    result = parse_document(payload, "application/pdf")
    assert result.blocks[0]["text"] == "Respect boundaries"
    assert result.blocks[0]["page_number"] == 1
    assert result.blocks[0]["source_locator"] == {"page": 1}


def test_mime_mismatch_and_eicar_are_rejected() -> None:
    with pytest.raises(Exception, match="match"):
        validate_upload(b"%PDF-invalid", "text/plain")
    with pytest.raises(Exception, match="malware"):
        validate_upload(
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
            "text/plain",
        )
