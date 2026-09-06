"""
Document Intelligence — extracts plain text from an uploaded PDF, DOCX,
PPTX, or XLSX so it can be referenced alongside a database analysis (BUILD
SPEC section 19). This is text/table extraction, not comprehension: it
turns a file into text the insight-explanation LLM step can read, exactly
the way it already reads computed metrics — nothing here interprets,
summarizes, or validates the document's content.

One deliberate, narrow exception: a real embedded picture (PDF/PPTX only
— see extract_pdf/extract_pptx) has no text form to "extract" at all, so
describing what it actually shows is the only way its content reaches
the rest of the pipeline. `_describe_images()` below is a small, tightly-
scoped AI vision call for exactly that (and only that) — not analysis of
the document as a whole, and explicitly told never to invent a number or
word it can't actually read in the image. Everything else in this module
is still pure extraction with zero interpretation.

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

OCR fallback for scanned/image-only PDF pages: pypdf only reads an
embedded text layer, so a genuinely scanned page (a photo/scan with no
text layer at all) used to extract to nothing, silently. Now, any page
whose native extraction comes back empty is rendered to an image
(PyMuPDF - no external renderer binary needed, unlike poppler) and
run through Tesseract (pytesseract - a real external OCR engine binary,
NOT pip-installable on its own; see docs/OCR.md for the one system-level
install step this needs, already wired into backend/Dockerfile for
production). Deliberately per-PAGE, not per-document: a mixed PDF (some
real text pages, some scanned pages - a common real-world shape, e.g. a
native report with a scanned signature page appended) gets native
extraction for the pages that have it and OCR only for the pages that
need it, rather than an all-or-nothing choice. Bounded by
MAX_OCR_PAGES_PER_DOCUMENT since OCR is genuinely CPU-expensive (roughly
1-3s/page at the DPI used here) unlike the near-instant native path, and
this upload endpoint is still synchronous - no background job queue
exists in this app to hand slow work off to, so an unbounded scanned PDF
could otherwise stall the request for minutes. Fails open, not closed, if
Tesseract isn't installed on the machine at all (TesseractNotFoundError):
falls back to the pre-OCR behavior (empty text for that page, surfaced
honestly, never pretending it worked) rather than crashing the upload -
same "a missing optional capability degrades, it doesn't break the app"
pattern already used for Redis and the Anthropic client elsewhere in this
app.

Still NOT built: real PDF table structure (text extraction, OCR'd or
native, flattens tables into reading-order text, which reads poorly for
anything but simple layouts - a known, unfixed limitation, not a bug).
"""
import base64
import io
import json
import logging
import zipfile
from dataclasses import dataclass

import pypdf
import docx
import openpyxl
import pptx
from pptx.enum.shapes import MSO_SHAPE_TYPE
import pytesseract
import pymupdf
from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger("meridian.ocr")

if settings.tesseract_cmd:
    # Only needed where Tesseract isn't already resolvable on PATH - e.g.
    # local Windows dev, where its installer doesn't always add itself to
    # PATH for an already-open shell. The Linux/Docker production target
    # (backend/Dockerfile installs tesseract-ocr via apt) needs no
    # override at all; PATH resolution just works there.
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

# A separate client instance from insight_agent.py's own _client - this
# module's job (per its docstring) is extraction, not comprehension, and
# describing an embedded picture is a real, if small, exception to that:
# there's no way to "extract" a photo or chart as text without actually
# looking at it. Kept as its own client/prompt here rather than importing
# insight_agent.py's, so the two stay decoupled - this one has a
# completely different, much narrower job (describe what's visibly in an
# image, nothing else) than insight_agent.py's actual analytical
# reasoning. Same fail-open pattern as a missing Tesseract install below:
# no key configured means images are still extracted, just never
# described - never a failed or degraded-looking upload over it.
_vision_client = Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

MAX_IMAGES_DESCRIBED_PER_DOCUMENT = 20
# Below this on either side, an embedded image is almost always a
# decorative icon, bullet glyph, or logo, not something with real
# analyzable content - skipped so a heavily-styled deck's icons don't
# burn through the per-document image budget before a real chart or
# photo gets a turn.
MIN_IMAGE_DIMENSION_PX = 80
# Resized to fit within this before sending - keeps the request small
# and fast without a meaningful loss of the kind of detail a factual
# description actually needs (this is "what does this show", not OCR of
# fine print).
MAX_IMAGE_SIDE_PX = 1024

_IMAGE_DESCRIPTION_SYSTEM_PROMPT = """You are describing images extracted from a document, so their
content can be referenced during analysis alongside the document's own text and tables - the same
job document_intelligence.py already does for those, just for pictures instead.

You will be given one or more images, each preceded by a label ("Image 1:", "Image 2:", ...).
For each one, write one factual, specific description of what it actually shows: a chart's
approximate data or trend, a diagram's structure, a photo's real subject, any text visible in it.
If an image is purely decorative (a logo, a background pattern, a bullet icon) with no
informational content, say so briefly rather than inventing meaning it doesn't have.

Never fabricate a specific number, label, or word you cannot actually read in the image - if a
chart's exact values aren't legible, describe the general shape or trend instead of guessing
precise figures. This is the same "never invent a fact" rule the rest of this application already
applies everywhere else it deals with a document's real content.

Respond ONLY with a JSON array of strings, exactly one per image, in the same order given:
["description of image 1", "description of image 2", ...]
"""


def _downsize_image_for_description(image_bytes: bytes) -> tuple[bytes, str] | None:
    """Returns (jpeg_bytes, media_type) resized to fit within
    MAX_IMAGE_SIDE_PX, or None if the bytes can't be decoded as an image
    at all - an unusual or corrupt embedded image is skipped rather than
    crashing the whole extraction over one bad picture, the same
    fails-open-per-item discipline _ocr_page already uses per page."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_SIDE_PX, MAX_IMAGE_SIDE_PX))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return None


def _describe_images(raw_images: list[bytes]) -> list[str]:
    """One batched vision call describing every image at once, rather
    than one call per image - far cheaper and faster, and lets the model
    reference images relative to each other if that's useful context.
    Fails open (returns []) with no Anthropic key configured, or if the
    call/parse fails for any reason - a document's images just come back
    without descriptions, never a failed upload over it."""
    if _vision_client is None or not raw_images:
        return []
    downsized = [d for d in (_downsize_image_for_description(r) for r in raw_images) if d is not None]
    if not downsized:
        return []
    content = []
    for i, (jpeg_bytes, media_type) in enumerate(downsized, start=1):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(jpeg_bytes).decode()},
        })
    try:
        resp = _vision_client.messages.create(
            model=settings.llm_model_fast,
            max_tokens=2048,
            system=_IMAGE_DESCRIPTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        text_out = "".join(b.text for b in resp.content if b.type == "text")
        stripped = text_out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        descriptions = json.loads(stripped)
        if isinstance(descriptions, list):
            # Never more than what was actually sent, regardless of what
            # the model's own array length claims to be.
            return [str(d) for d in descriptions][:len(downsized)]
    except Exception:
        logger.warning("Image description failed for this document - continuing without it.", exc_info=True)
    return []

MAX_EXTRACTED_CHARS = 50_000  # bounds LLM context cost the same way row limits bound query cost
MAX_XLSX_ROWS_PER_SHEET = 200
MAX_XLSX_SHEETS = 10
MAX_PPTX_SLIDES = 200
MAX_OCR_PAGES_PER_DOCUMENT = 15
OCR_RENDER_DPI = 200  # balance of accuracy vs. render+recognition time
# A page's native extraction shorter than this is treated as "probably
# scanned, not just a sparse page" and gets OCR'd - a real PDF page with
# only a few words of genuine text is rare enough that this heuristic
# costs little precision while catching the common case (an image-only
# page returns "" or a handful of stray characters from decorative
# elements, never a real sentence).
NATIVE_TEXT_MIN_CHARS = 20

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}

# DOCX/XLSX/PPTX (Office Open XML) are plain ZIP archives when unprotected.
# A password-protected one is instead wrapped in the much older OLE2/
# Compound File Binary Format container (the same container legacy
# .doc/.xls/.ppt used) - recognizable from its first 8 bytes alone, well
# before ever attempting to unzip/parse it. This is the same
# signature-based detection msoffcrypto-tool and similar libraries use;
# no new dependency is needed just to DETECT it (only decrypting one
# would need that, which this app doesn't attempt - a locked file is
# rejected with instructions to unlock and re-upload, not decrypted).
_OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# A legitimate Office file rarely compresses beyond roughly 20-50x; a
# ratio far past that on any single internal part is the classic "zip
# bomb" red flag - a small file that expands to an enormous one once
# decompressed, aimed at exhausting memory/CPU the moment
# openpyxl/python-docx/python-pptx actually reads it.
_MAX_ZIP_ENTRY_COMPRESSION_RATIO = 200
_MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 500_000_000  # nothing legitimate here needs to expand past 500MB


class UnsupportedDocumentType(Exception):
    pass


class DocumentTooLarge(Exception):
    pass


class LockedDocumentError(Exception):
    """The file is password-protected/encrypted and this app made no
    attempt to guess or crack the password - the user is the one who can
    actually remove it, so the fix is always "unlock it and re-upload,"
    surfaced as a clear, specific error rather than a confusing parse
    failure or (worse) silently extracting nothing."""
    pass


class UnsafeDocumentError(Exception):
    """The file failed a basic pre-parse safety check (see
    _check_ooxml_zip_safety below) - flagged and rejected before this app
    attempts to actually decompress/parse it, not after."""
    pass


def _check_ooxml_not_locked(file_bytes: bytes, kind: str) -> None:
    if file_bytes[:8] == _OLE2_SIGNATURE:
        raise LockedDocumentError(
            f"This {kind.upper()} file appears to be password-protected. Please remove the "
            "password (in most Office apps: File > Info > Protect Document/Workbook/"
            "Presentation > Remove Password, or re-save a copy without one) and upload it again."
        )


def _check_ooxml_zip_safety(file_bytes: bytes) -> None:
    """Reads each zip entry's own declared compressed/uncompressed sizes
    from the archive's central directory - metadata every zip file
    carries regardless of content - without decompressing a single byte
    of actual data. Bad-zip errors are deliberately NOT caught here: by
    the time this runs, _check_ooxml_not_locked has already ruled out
    "it's actually a password-protected OLE2 container" as the
    explanation, so a file that still isn't a valid zip at this point is
    genuinely corrupt, and the normal extraction attempt right after this
    will raise its own clear error for that instead."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        total_uncompressed = 0
        for info in zf.infolist():
            if info.compress_size > 0 and info.file_size / info.compress_size > _MAX_ZIP_ENTRY_COMPRESSION_RATIO:
                raise UnsafeDocumentError(
                    "This file failed a basic safety check (one of its internal parts has an "
                    "unusually extreme compression ratio) and was not opened. If this is a file "
                    "you created yourself in Office or Google Workspace, try re-saving a fresh copy."
                )
            total_uncompressed += info.file_size
        if total_uncompressed > _MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
            raise UnsafeDocumentError(
                "This file failed a basic safety check (it would expand to an unreasonably large "
                "size once opened) and was not opened."
            )


@dataclass
class ExtractionResult:
    text: str
    truncated: bool
    # Meaning depends on kind: page count for PDF, paragraph count for
    # DOCX, sheet count for XLSX — informational only, shown in the UI.
    source_unit_count: int
    # How many pages' text came from OCR rather than a native text layer
    # (PDF only; always 0 for every other kind). Surfaced to the caller so
    # the UI can show "(N page(s) OCR'd)" - OCR'd text is real but lower-
    # confidence than a native text layer (misreads happen), worth
    # flagging rather than presenting identically to a clean extraction.
    ocr_pages_used: int = 0
    # How many embedded pictures (PDF/PPTX only; always 0 for DOCX/XLSX -
    # see this module's docstring for why) got a real AI-generated
    # description folded into the extracted text. Surfaced the same way
    # ocr_pages_used already is, since this is the same category of
    # "real, but different in kind from a native text extraction" signal
    # - an image description is the AI's read of what it visually shows,
    # not ground truth pulled directly off the page the way native text
    # is.
    images_described: int = 0


def _truncate(text: str) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text, False
    return text[:MAX_EXTRACTED_CHARS], True


def _ocr_page(pdf_doc, page_index: int) -> str:
    """Renders one page to an image and runs Tesseract on it. Returns ""
    (not an exception) on any OCR-specific failure - a page that can't be
    OCR'd degrades to "no text from this page", the same honest-empty
    result a scanned page without this fallback at all would have
    produced, never a crash that takes down the whole upload over one
    bad page."""
    try:
        page = pdf_doc[page_index]
        pix = page.get_pixmap(dpi=OCR_RENDER_DPI)
        image_bytes = pix.tobytes("png")
        from PIL import Image
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image).strip()
    except pytesseract.TesseractNotFoundError:
        # Not installed on this machine at all - fail open for the WHOLE
        # document, not just this page (every subsequent OCR attempt
        # would hit the identical error), by re-raising a marker the
        # caller checks for once and stops trying further pages.
        raise
    except Exception as e:
        logger.warning("OCR failed for page %d, treating as empty: %s", page_index, e)
        return ""


def extract_pdf(file_bytes: bytes) -> ExtractionResult:
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        # Many "encrypted" PDFs only restrict printing/editing via an
        # owner password, with a blank USER password - genuinely readable
        # without ever prompting anyone. Try that blank password first;
        # only reject as locked if the PDF still can't be opened after
        # trying it, which means a REAL password is required.
        try:
            decrypted = reader.decrypt("")
        except Exception:
            decrypted = 0
        if not decrypted:
            raise LockedDocumentError(
                "This PDF is password-protected. Please remove the password (most PDF "
                "viewers can save an unprotected copy) and upload it again."
            )
    pages_text = [page.extract_text() or "" for page in reader.pages]

    # A single pymupdf handle serves both the OCR fallback below (needs
    # it to rasterize a scanned page) and image extraction just after -
    # opened unconditionally now (it used to open only when OCR was
    # actually needed) since a PDF with a perfectly good native text
    # layer can still have real embedded pictures worth describing.
    ocr_pages_used = 0
    images_described = 0
    pdf_doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        candidates = [i for i, t in enumerate(pages_text) if len(t.strip()) < NATIVE_TEXT_MIN_CHARS]
        if candidates:
            tesseract_available = True
            for i in candidates[:MAX_OCR_PAGES_PER_DOCUMENT]:
                if not tesseract_available:
                    break
                try:
                    ocr_text = _ocr_page(pdf_doc, i)
                except pytesseract.TesseractNotFoundError:
                    logger.warning("Tesseract is not installed on this machine - OCR fallback skipped "
                                    "for the rest of this document (and every document until it is).")
                    tesseract_available = False
                    continue
                if ocr_text:
                    pages_text[i] = ocr_text
                    ocr_pages_used += 1

        # Real embedded pictures - a chart, a photo, a diagram - not just
        # the page's text layer. Deduplicated by xref: the same logo
        # embedded once but referenced on every page would otherwise be
        # "described" (and billed) once per page it appears on. The whole
        # block is its own try/except, on top of _describe_images' own
        # internal one: pages_text (including any OCR results already
        # merged into it above) has already been successfully produced
        # by this point, and nothing about images should ever be able to
        # take that down with it - the same outer-safety-net gap a real
        # test caught in extract_xlsx's equivalent code, fixed the same
        # way here for consistency rather than assumed safe just because
        # the callee also has its own try/excepts.
        try:
            seen_xrefs: set[int] = set()
            raw_images: list[bytes] = []
            image_pages: list[int] = []
            for page_index in range(len(pdf_doc)):
                for img_info in pdf_doc.get_page_images(page_index):
                    xref = img_info[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        extracted = pdf_doc.extract_image(xref)
                    except Exception:
                        continue
                    if (extracted.get("width", 0) < MIN_IMAGE_DIMENSION_PX
                            or extracted.get("height", 0) < MIN_IMAGE_DIMENSION_PX):
                        continue  # almost certainly a decorative icon/logo, not real content
                    raw_images.append(extracted["image"])
                    image_pages.append(page_index + 1)
                    if len(raw_images) >= MAX_IMAGES_DESCRIBED_PER_DOCUMENT:
                        break
                if len(raw_images) >= MAX_IMAGES_DESCRIBED_PER_DOCUMENT:
                    break

            descriptions = _describe_images(raw_images)
            images_described = len(descriptions)
            if descriptions:
                pages_text.append("\n--- Images ---")
                for page_no, desc in zip(image_pages, descriptions):
                    pages_text.append(f"[Image on page {page_no}]: {desc}")
        except Exception:
            logger.warning("PDF image extraction/description failed - continuing with text only.", exc_info=True)
    finally:
        pdf_doc.close()

    text, truncated = _truncate("\n\n".join(pages_text))
    return ExtractionResult(
        text=text, truncated=truncated, source_unit_count=len(reader.pages),
        ocr_pages_used=ocr_pages_used, images_described=images_described,
    )


def extract_docx(file_bytes: bytes) -> ExtractionResult:
    document = docx.Document(io.BytesIO(file_bytes))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    text, truncated = _truncate("\n".join(parts))
    return ExtractionResult(text=text, truncated=truncated, source_unit_count=len(document.paragraphs))


def _extract_xlsx_images(file_bytes: bytes) -> tuple[list[bytes], list[str]]:
    """openpyxl's embedded-image access (worksheet._images) simply isn't
    available in the read_only=True streaming mode extract_xlsx uses for
    cell text (confirmed directly - a ReadOnlyWorksheet doesn't even have
    the attribute) - a genuinely separate, normal-mode load is the only
    way to reach it. That's a real, if bounded, cost the read_only mode
    was chosen specifically to avoid for a large sheet's cell data - but
    by this point the file has already passed the 20MB upload cap and
    the zip-bomb ratio check (see _check_ooxml_zip_safety), so the
    "unbounded blow-up" risk that mode was guarding against is already
    ruled out; what's left is ordinary parse time for an already
    size-capped file. Fails open on ANY error (a malformed drawing part,
    an image openpyxl can't resolve, or an unexpected structural quirk)
    - the text extraction from the read_only pass already succeeded
    independently, so a problem here costs the document its image
    descriptions, never the whole upload."""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception:
        return [], []
    images, labels = [], []
    try:
        for sheet in workbook.worksheets[:MAX_XLSX_SHEETS]:
            for img in getattr(sheet, "_images", []):
                if len(images) >= MAX_IMAGES_DESCRIBED_PER_DOCUMENT:
                    return images, labels
                try:
                    data = img._data()
                    if img.width < MIN_IMAGE_DIMENSION_PX or img.height < MIN_IMAGE_DIMENSION_PX:
                        continue
                    cell_ref = "?"
                    try:
                        from openpyxl.utils import get_column_letter
                        anchor = img.anchor._from
                        cell_ref = f"{get_column_letter(anchor.col + 1)}{anchor.row + 1}"
                    except Exception:
                        pass
                    images.append(data)
                    labels.append(f"sheet '{sheet.title}', near {cell_ref}")
                except Exception:
                    continue
    finally:
        workbook.close()
    return images, labels


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

    # An outer safety net on top of _extract_xlsx_images' own internal
    # error handling, not a substitute for it: the cell text above has
    # already been successfully extracted by this point, and nothing
    # about images should ever be able to take that down with it -
    # caught directly by a test patching this call to raise unexpectedly,
    # not assumed safe just because the callee also has its own
    # try/excepts.
    images_described = 0
    try:
        raw_images, image_labels = _extract_xlsx_images(file_bytes)
        descriptions = _describe_images(raw_images)
        images_described = len(descriptions)
        if descriptions:
            parts.append("--- Images ---")
            for label, desc in zip(image_labels, descriptions):
                parts.append(f"[Image in {label}]: {desc}")
    except Exception:
        logger.warning("XLSX image extraction/description failed - continuing with text only.", exc_info=True)

    text, char_truncated = _truncate("\n".join(parts))
    truncated = char_truncated or row_truncated or sheets_included < total_sheets
    return ExtractionResult(
        text=text, truncated=truncated, source_unit_count=total_sheets, images_described=images_described,
    )


def extract_pptx(file_bytes: bytes) -> ExtractionResult:
    presentation = pptx.Presentation(io.BytesIO(file_bytes))
    total_slides = len(presentation.slides)
    slides_included = 0
    parts = []
    raw_images: list[bytes] = []
    image_slides: list[int] = []
    for i, slide in enumerate(presentation.slides):
        if i >= MAX_PPTX_SLIDES:
            break
        slides_included += 1
        parts.append(f"--- Slide {i + 1} ---")
        for shape in slide.shapes:
            # Title/body text boxes, and any other shape with a text
            # frame (a caption, a text box someone dragged in, etc).
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        parts.append(text)
            # Tables render the same "cell | cell" flattening as
            # extract_docx's tables, for consistency across formats.
            if shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
            # Real embedded pictures - a photo, a chart pasted in as an
            # image, a diagram - not just the slide's own text shapes.
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and len(raw_images) < MAX_IMAGES_DESCRIBED_PER_DOCUMENT:
                try:
                    width, height = shape.image.size
                    if width >= MIN_IMAGE_DIMENSION_PX and height >= MIN_IMAGE_DIMENSION_PX:
                        raw_images.append(shape.image.blob)
                        image_slides.append(i + 1)
                except Exception:
                    pass  # an unusual/corrupt embedded image is skipped, not a crashed upload
        # Speaker notes often carry real analytical content (the actual
        # narration a deck's bullet points only hint at) - included, but
        # clearly labelled so it's obvious in the extracted text which
        # part was on-slide vs. notes-only.
        if slide.has_notes_slide:
            notes_text = (slide.notes_slide.notes_text_frame.text or "").strip()
            if notes_text:
                parts.append(f"[Speaker notes] {notes_text}")

    # Same outer safety net as extract_pdf/extract_xlsx: parts already
    # holds every slide's real text/tables/notes by this point, and
    # nothing about images should ever be able to take that down with it.
    images_described = 0
    try:
        descriptions = _describe_images(raw_images)
        images_described = len(descriptions)
        if descriptions:
            parts.append("--- Images ---")
            for slide_no, desc in zip(image_slides, descriptions):
                parts.append(f"[Image on slide {slide_no}]: {desc}")
    except Exception:
        logger.warning("PPTX image description failed - continuing with text only.", exc_info=True)

    text, char_truncated = _truncate("\n".join(parts))
    truncated = char_truncated or slides_included < total_slides
    return ExtractionResult(
        text=text, truncated=truncated, source_unit_count=total_slides, images_described=images_described,
    )


def extract(filename: str, file_bytes: bytes) -> tuple[str, ExtractionResult]:
    """Dispatches on file extension. Returns (kind, ExtractionResult).
    Safety/lock checks run BEFORE any real parsing, in the same spirit as
    this app's other upfront gates (the size cap in routes_documents.py
    runs before this function is even called) - a locked or unsafe file
    is rejected with a specific, actionable reason, not a generic parse
    failure or, worse, silently extracted as empty."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = SUPPORTED_EXTENSIONS.get(ext)
    if kind is None:
        raise UnsupportedDocumentType(
            f"Unsupported file type '{ext or filename}'. Supported: "
            f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )
    if kind in ("docx", "xlsx", "pptx"):
        _check_ooxml_not_locked(file_bytes, kind)
        _check_ooxml_zip_safety(file_bytes)
    if kind == "pdf":
        return kind, extract_pdf(file_bytes)
    if kind == "docx":
        return kind, extract_docx(file_bytes)
    if kind == "pptx":
        return kind, extract_pptx(file_bytes)
    return kind, extract_xlsx(file_bytes)
