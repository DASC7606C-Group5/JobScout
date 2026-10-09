"""Extract the name and text of uploaded resume files for profile creation."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from docx import Document
from docx.document import Document as WordDocument
from docx.section import _Footer, _Header
from docx.table import _Cell
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError

from jobscout.config import get_settings
from jobscout.schemas.session import ResumeInput

MAX_PDF_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
SUPPORTED_EXTENSIONS = frozenset({".txt", ".pdf", ".docx"})


class ResumeParseError(ValueError):
    """A user-facing file validation or extraction failure."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def validate_resume_name(filename: str | None) -> tuple[str, str]:
    """Discard browser-supplied paths and select a parser by extension."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name.strip()
    extension = PurePosixPath(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ResumeParseError(
            "unsupported_format", "Upload your resume as a PDF, DOCX, or UTF-8 TXT file.", 415
        )
    return name, extension


def _extract_pdf(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise ResumeParseError(
            "invalid_file", "This is not a valid PDF. Export the file again and upload it."
        )
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise ResumeParseError(
            "encrypted_file",
            "This PDF is password-protected. Remove the password and upload it again.",
        )
    if len(reader.pages) > get_settings().resume_max_pdf_pages:
        raise ResumeParseError(
            "document_too_large",
            f"This PDF has too many pages. The limit is {get_settings().resume_max_pdf_pages} pages.",
        )
    parts: list[str] = []
    length = 0
    uncompressed_bytes = 0
    for page in reader.pages:
        contents = page.get_contents()
        if contents is not None:
            uncompressed_bytes += len(contents.get_data())
            if uncompressed_bytes > MAX_PDF_UNCOMPRESSED_BYTES:
                raise ResumeParseError(
                    "document_too_large", "The PDF is too large. Shorten it and upload it again."
                )
        part = page.extract_text() or ""
        length += len(part)
        if length > get_settings().resume_max_text_characters:
            raise ResumeParseError(
                "text_too_long",
                f"The resume exceeds the {get_settings().resume_max_text_characters:,} character limit.",
            )
        parts.append(part)
    text = "\n".join(parts)
    if not text.strip():
        raise ResumeParseError(
            "no_extractable_text",
            "This PDF contains no extractable text and may be a scan. Run OCR first, or upload a DOCX or TXT version.",
        )
    return text


def _word_blocks(
    container: WordDocument | _Cell | _Header | _Footer, depth: int = 0
) -> Iterator[str]:
    if depth > 10:
        raise ResumeParseError(
            "document_too_large",
            "The DOCX contains too many nested tables. Simplify the document and upload it again.",
        )
    for block in container.iter_inner_content():
        if isinstance(block, Paragraph):
            yield block.text
        else:
            # Merged cells appear more than once in the table's rows.
            seen_cells: set[object] = set()
            for row in block.rows:
                for cell in row.cells:
                    if cell._tc not in seen_cells:
                        seen_cells.add(cell._tc)
                        yield from _word_blocks(cell, depth + 1)


def _extract_docx(content: bytes) -> str:
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or sum(e.file_size for e in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise ResumeParseError(
                "document_too_large", "The DOCX is too large. Shorten it and upload it again."
            )
        if any(entry.flag_bits & 1 for entry in entries):
            raise ResumeParseError(
                "encrypted_file",
                "This DOCX is password-protected. Remove the password and upload it again.",
            )
        if "word/document.xml" not in archive.namelist():
            raise ResumeParseError("invalid_file", "This is not a valid DOCX document.")
    document = Document(BytesIO(content))
    containers: list[WordDocument | _Header | _Footer] = [document]
    for section in document.sections:
        for container in (
            section.header,
            section.first_page_header,
            section.even_page_header,
            section.footer,
            section.first_page_footer,
            section.even_page_footer,
        ):
            if not container.is_linked_to_previous:
                containers.append(container)
    parts: list[str] = []
    length = 0
    for part_container in containers:
        for part in _word_blocks(part_container):
            length += len(part) + bool(parts)
            if length > get_settings().resume_max_text_characters:
                raise ResumeParseError(
                    "text_too_long",
                    f"The resume exceeds the {get_settings().resume_max_text_characters:,} character limit.",
                )
            parts.append(part)
    return "\n".join(parts)


def parse_resume(filename: str | None, content: bytes) -> ResumeInput:
    """Parse without saving an original file or sending it to another service."""
    name, extension = validate_resume_name(filename)
    if len(content) > get_settings().resume_max_bytes:
        raise ResumeParseError(
            "file_too_large", "The file exceeds the configured upload size limit.", 413
        )
    if not content:
        raise ResumeParseError(
            "empty_file", "This file is empty. Check it and choose another file."
        )
    try:
        if extension == ".pdf":
            with apply_configuration(
                maximum_declared_stream_length=get_settings().resume_max_bytes,
                array_based_stream_maximum_output_length=MAX_PDF_UNCOMPRESSED_BYTES,
                zlib_maximum_output_length=MAX_PDF_UNCOMPRESSED_BYTES,
                lzw_maximum_output_length=MAX_PDF_UNCOMPRESSED_BYTES,
                run_length_maximum_output_length=MAX_PDF_UNCOMPRESSED_BYTES,
                page_tree_maximum_entries=1000,
                xform_maximum_invocations_per_extraction=500,
                jbig2dec_binary=None,
            ):
                text = _extract_pdf(content)
        elif extension == ".docx":
            text = _extract_docx(content)
        else:
            text = content.decode("utf-8-sig")
    except ResumeParseError:
        raise
    except LimitReachedError as error:
        raise ResumeParseError(
            "document_too_large", "The PDF is too large. Shorten it and upload it again."
        ) from error
    except UnicodeDecodeError as error:
        raise ResumeParseError(
            "invalid_encoding", "The file encoding could not be read. Use a UTF-8 encoded TXT file."
        ) from error
    except Exception as error:
        # Parser diagnostics can contain file contents; return only a fixed message.
        raise ResumeParseError(
            "invalid_file",
            "This document could not be parsed. Make sure it opens correctly, then export and upload it again.",
        ) from error
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ResumeParseError(
            "empty_text", "This file contains no text. Check it and choose another file."
        )
    if "\x00" in text or "\ufffd" in text:
        raise ResumeParseError(
            "invalid_text",
            "The text could not be read correctly. Check the file encoding or export the document again.",
        )
    if len(text) > get_settings().resume_max_text_characters:
        raise ResumeParseError(
            "text_too_long",
            f"The resume exceeds the {get_settings().resume_max_text_characters:,} character limit.",
        )
    return ResumeInput(name=name, text=text)
