from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_RESUME_TEXT_CHARACTERS = 250_000
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_DOCX_ENTRIES = 512
MAX_PDF_PAGES = 100
PARSER_VERSION = "1.0.0"
PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class UnsupportedResumeType(ValueError):
    pass


class InvalidResumeDocument(ValueError):
    pass


class ResumeFileTooLarge(ValueError):
    pass


class ResumeParser:
    @staticmethod
    def safe_file_name(file_name: str) -> str:
        normalized = file_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
        normalized = unicodedata.normalize("NFKC", normalized)
        if not normalized or len(normalized) > 255 or "\x00" in normalized:
            raise InvalidResumeDocument("The uploaded file name is invalid.")
        return normalized

    @classmethod
    def parse(cls, file_name: str, content_type: str, data: bytes) -> tuple[str, str]:
        safe_name = cls.safe_file_name(file_name)
        if not data:
            raise InvalidResumeDocument("The uploaded resume is empty.")
        if len(data) > MAX_RESUME_BYTES:
            raise ResumeFileTooLarge("Resume files must be 5 MiB or smaller.")
        extension = PurePosixPath(safe_name).suffix.casefold()
        normalized_type = content_type.split(";", maxsplit=1)[0].strip().casefold()
        if extension == ".pdf" and normalized_type == PDF_CONTENT_TYPE:
            text = cls._parse_pdf(data)
        elif extension == ".docx" and normalized_type == DOCX_CONTENT_TYPE:
            text = cls._parse_docx(data)
        else:
            raise UnsupportedResumeType("Upload a PDF or DOCX file with a matching content type.")
        normalized_text = cls._normalize_text(text)
        if not normalized_text:
            raise InvalidResumeDocument("No readable text was found in the resume.")
        if len(normalized_text) > MAX_RESUME_TEXT_CHARACTERS:
            raise InvalidResumeDocument(
                "Extracted resume text exceeds the 250,000 character limit."
            )
        return safe_name, normalized_text

    @staticmethod
    def _parse_pdf(data: bytes) -> str:
        if not data.startswith(b"%PDF-"):
            raise InvalidResumeDocument("The uploaded file is not a valid PDF document.")
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise InvalidResumeDocument("Encrypted PDF resumes are not supported.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise InvalidResumeDocument("PDF resumes must contain no more than 100 pages.")
            extracted_pages: list[str] = []
            text_length = 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text_length += len(page_text)
                if text_length > MAX_RESUME_TEXT_CHARACTERS:
                    raise InvalidResumeDocument(
                        "Extracted resume text exceeds the 250,000 character limit."
                    )
                extracted_pages.append(page_text)
            return "\n".join(extracted_pages)
        except InvalidResumeDocument:
            raise
        except (PdfReadError, ValueError, KeyError, OSError) as exc:
            raise InvalidResumeDocument("The PDF resume could not be parsed.") from exc

    @staticmethod
    def _parse_docx(data: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_DOCX_ENTRIES:
                    raise InvalidResumeDocument(
                        "The DOCX resume contains too many archive entries."
                    )
                if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise InvalidResumeDocument(
                        "The DOCX resume expands beyond the safe size limit."
                    )
                names = {entry.filename for entry in entries}
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise InvalidResumeDocument(
                        "The DOCX resume is missing required document parts."
                    )
                ElementTree.fromstring(archive.read("[Content_Types].xml"))
                document = archive.read("word/document.xml")
            root = ElementTree.fromstring(document)
            if root.tag != f"{{{_WORD_NAMESPACE}}}document":
                raise InvalidResumeDocument("The DOCX resume has an invalid document root.")
        except InvalidResumeDocument:
            raise
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError) as exc:
            raise InvalidResumeDocument("The DOCX resume could not be parsed.") from exc
        paragraphs: list[str] = []
        for paragraph in root.iter(f"{{{_WORD_NAMESPACE}}}p"):
            value = "".join(node.text or "" for node in paragraph.iter(f"{{{_WORD_NAMESPACE}}}t"))
            if value:
                paragraphs.append(value)
        return "\n".join(paragraphs)

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text).replace("\x00", "")
        lines = [re.sub(r"[\t ]+", " ", line).strip() for line in normalized.splitlines()]
        return "\n".join(line for line in lines if line).strip()
