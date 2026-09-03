"""
Document Intelligence — extracts plain text from an uploaded PDF, DOCX, or
XLSX so it can be referenced alongside a database analysis (BUILD SPEC
section 19). This is text/table extraction, not comprehension: it turns a
file into text the insight-explanation LLM step can read, exactly the way
it already reads computed metrics — nothing here interprets, summarizes, or
validates the document's content.

Security note this module exists specifically to keep in view: extracted
document text is the first genuinely externally-authored content this app
ever hands to an LLM. Row values and schema field names are trusted enough
(they come from a database the tenant connected and authorized), but a
document a user uploads could contain anything, including text specifically
crafted to look like instructions ("ignore your previous instructions and
...", "SYSTEM:", etc.). Per app/agents/planner.py's prompt-injection
defence, this text must always be handed to the LLM as a labelled,
untrusted DATA payload the model is told to reference, never blended into
instruction text — see how app/agents/insight_agent.py passes it. This
module's job stops at extraction; it does not decide how the text is used
downstream.

Deliberately NOT built: OCR for scanned/image-only PDFs (pypdf only reads
an embedded text layer — a scanned document with no text layer extracts to
nothing, silently, and that's surfaced to the caller as an empty/near-empty
result rather than pretending it worked), and real PDF table structure
(text extraction flattens tables into reading-order text, which reads
poorly for anything but simple layouts — a known, unfixed limitation, not
a bug).
"""
import io
from dataclasses import dataclass

import pypdf
import docx
import openpyxl

MAX_EXTRACTED_CHARS = 50_000  # bounds LLM context cost the same way row limits bound query cost
MAX_XLSX_ROWS_PER_SHEET = 200
MAX_XLSX_SHEETS = 10

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx"}


class UnsupportedDocumentType(Exception):
    pass


class DocumentTooLarge(Exception):
    pass


@dataclass
class ExtractionResult:
    text: str
    truncated: bool
    # Meaning depends on kind: page count for PDF, paragraph count for
    # DOCX, sheet count for XLSX — informational only, shown in the UI.
    source_unit_count: int


def _truncate(text: str) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text, False
    return text[:MAX_EXTRACTED_CHARS], True


def extract_pdf(file_bytes: bytes) -> ExtractionResult:
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    text, truncated = _truncate("\n\n".join(pages_text))
    return ExtractionResult(text=text, truncated=truncated, source_unit_count=len(reader.pages))


def extract_docx(file_bytes: bytes) -> ExtractionResult:
    document = docx.Document(io.BytesIO(file_bytes))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    text, truncated = _truncate("\n".join(parts))
    return ExtractionResult(text=text, truncated=truncated, source_unit_count=len(document.paragraphs))


def extract_xlsx(file_bytes: bytes) -> ExtractionResult:
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    total_sheets = len(workbook.worksheets)
    sheets_included = 0
    row_truncated = False
    parts = []
    for sheet in workbook.worksheets[:MAX_XLSX_SHEETS]:
        sheets_included += 1
        parts.append(f"--- Sheet: {sheet.title} ---")
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= MAX_XLSX_ROWS_PER_SHEET:
                parts.append(f"... (more rows omitted, showing first {MAX_XLSX_ROWS_PER_SHEET})")
                row_truncated = True
                break
            parts.append(" | ".join("" if v is None else str(v) for v in row))
    workbook.close()
    text, char_truncated = _truncate("\n".join(parts))
    truncated = char_truncated or row_truncated or sheets_included < total_sheets
    return ExtractionResult(text=text, truncated=truncated, source_unit_count=total_sheets)


def extract(filename: str, file_bytes: bytes) -> tuple[str, ExtractionResult]:
    """Dispatches on file extension. Returns (kind, ExtractionResult)."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = SUPPORTED_EXTENSIONS.get(ext)
    if kind is None:
        raise UnsupportedDocumentType(
            f"Unsupported file type '{ext or filename}'. Supported: "
            f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )
    if kind == "pdf":
        return kind, extract_pdf(file_bytes)
    if kind == "docx":
        return kind, extract_docx(file_bytes)
    return kind, extract_xlsx(file_bytes)
