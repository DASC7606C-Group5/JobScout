"""Extract uploaded resume files into the existing name/text workflow contract."""

from collections.abc import Iterator
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from docx import Document
from docx.document import Document as WordDocument
from docx.section import _Footer, _Header
from docx.table import _Cell
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from jobscout.schemas.session import ResumeInput

MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_RESUME_TEXT_LENGTH = 100_000
MAX_PDF_PAGES = 50
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
        raise ResumeParseError("unsupported_format", "请上传 PDF、DOCX 或 UTF-8 TXT 简历。", 415)
    return name, extension


def _extract_pdf(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise ResumeParseError("invalid_file", "文件内容不是有效的 PDF，请重新导出后上传。")
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise ResumeParseError("encrypted_file", "这份 PDF 已加密，请移除密码后重新上传。")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ResumeParseError("document_too_large", "PDF 页数过多，请上传 50 页以内的简历。")
    parts: list[str] = []
    length = 0
    for page in reader.pages:
        part = page.extract_text() or ""
        length += len(part)
        if length > MAX_RESUME_TEXT_LENGTH:
            raise ResumeParseError("text_too_long", "简历文字过多，请精简至 100,000 字以内。")
        parts.append(part)
    text = "\n".join(parts)
    if not text.strip():
        raise ResumeParseError(
            "no_extractable_text",
            "这份 PDF 没有可提取的文字，可能是扫描件；请先进行 OCR，或上传 DOCX / TXT 版本。",
        )
    return text


def _word_blocks(
    container: WordDocument | _Cell | _Header | _Footer, depth: int = 0
) -> Iterator[str]:
    if depth > 10:
        raise ResumeParseError("document_too_large", "DOCX 表格嵌套过多，请简化文档后上传。")
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
            raise ResumeParseError("document_too_large", "DOCX 文档内容过大，请精简后上传。")
        if any(entry.flag_bits & 1 for entry in entries):
            raise ResumeParseError("encrypted_file", "这份 DOCX 已加密，请移除密码后重新上传。")
        if "word/document.xml" not in archive.namelist():
            raise ResumeParseError("invalid_file", "文件内容不是有效的 DOCX 文档。")
    document = Document(BytesIO(content))
    parts = list(_word_blocks(document))
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
                parts.extend(_word_blocks(container))
    return "\n".join(parts)


def parse_resume(filename: str | None, content: bytes) -> ResumeInput:
    """Parse without saving an original file or sending it to another service."""
    name, extension = validate_resume_name(filename)
    if len(content) > MAX_RESUME_BYTES:
        raise ResumeParseError("file_too_large", "文件过大，请选择 10 MB 以内的简历。", 413)
    if not content:
        raise ResumeParseError("empty_file", "这份文件为空，请检查后重新选择。")
    try:
        if extension == ".pdf":
            text = _extract_pdf(content)
        elif extension == ".docx":
            text = _extract_docx(content)
        else:
            text = content.decode("utf-8-sig")
    except ResumeParseError:
        raise
    except UnicodeDecodeError as error:
        raise ResumeParseError(
            "invalid_encoding", "无法读取文件编码，请使用 UTF-8 格式的 TXT 文件。"
        ) from error
    except Exception as error:
        # Parser diagnostics can contain file contents; return only a fixed message.
        raise ResumeParseError(
            "invalid_file", "无法解析这份文档，请确认文件可正常打开后重新导出上传。"
        ) from error
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ResumeParseError("empty_text", "这份文件没有文字，请检查后重新选择。")
    if "\x00" in text or "\ufffd" in text:
        raise ResumeParseError("invalid_text", "文字无法正确读取，请检查文件编码或重新导出文档。")
    if len(text) > MAX_RESUME_TEXT_LENGTH:
        raise ResumeParseError("text_too_long", "简历文字过多，请精简至 100,000 字以内。")
    return ResumeInput(name=name, text=text)
