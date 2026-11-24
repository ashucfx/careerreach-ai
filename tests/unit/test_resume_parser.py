from __future__ import annotations

import io
import zipfile

import pytest
from careerreach.resume_parser import (
    DOCX_CONTENT_TYPE,
    MAX_RESUME_BYTES,
    PDF_CONTENT_TYPE,
    InvalidResumeDocument,
    ResumeFileTooLarge,
    ResumeParser,
    UnsupportedResumeType,
)


def _docx(text: str) -> bytes:
    xml_text = "".join(f"<w:t>{part} </w:t>" for part in text.split(" "))
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p>{xml_text}</w:p></w:body></w:document>"
    )
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def test_docx_resume_text_is_extracted_and_file_name_is_sanitized() -> None:
    file_name, text = ResumeParser.parse(
        "..\\candidate.docx", DOCX_CONTENT_TYPE, _docx("Ashu Shukla Python")
    )

    assert file_name == "candidate.docx"
    assert text == "Ashu Shukla Python"


def test_pdf_resume_text_is_extracted() -> None:
    file_name, text = ResumeParser.parse(
        "candidate.pdf", PDF_CONTENT_TYPE, _pdf("Ashu Shukla Python engineer")
    )

    assert file_name == "candidate.pdf"
    assert "Ashu Shukla Python engineer" in text


def test_resume_parser_rejects_mismatched_types_and_unreadable_files() -> None:
    with pytest.raises(UnsupportedResumeType):
        ResumeParser.parse("candidate.pdf", DOCX_CONTENT_TYPE, _pdf("Candidate name"))

    with pytest.raises(InvalidResumeDocument):
        ResumeParser.parse("candidate.docx", DOCX_CONTENT_TYPE, b"not a zip file")


def test_resume_parser_rejects_files_over_the_size_limit() -> None:
    with pytest.raises(ResumeFileTooLarge):
        ResumeParser.parse("candidate.docx", DOCX_CONTENT_TYPE, b"x" * (MAX_RESUME_BYTES + 1))
