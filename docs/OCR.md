# OCR for scanned/image-only PDFs

`pypdf` (used for every other PDF) only reads a PDF's embedded text layer.
A genuinely scanned page — a photo or scan with no text layer at all —
used to extract to nothing, silently, with no indication anything had gone
wrong. `app/agents/document_intelligence.py` now fixes that: any page
whose native extraction comes back under 20 characters is rendered to an
image (via PyMuPDF — no external renderer binary needed, unlike poppler)
and run through Tesseract, a real external OCR engine. See that file's
module docstring for the full design (per-page not per-document, the
15-page cap, fail-open behavior if Tesseract isn't installed).

PyMuPDF and pytesseract are both pip packages already in
`requirements.txt` — nothing extra to install for them. **Tesseract itself
is not pip-installable** — it's a compiled binary the `pytesseract` package
just calls out to via subprocess. That binary is the one system-level
install step this feature needs.

## Production (Railway / Docker)

Nothing to do — `backend/Dockerfile` already installs it:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev freetds-dev tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
```

`apt`'s `tesseract-ocr` package puts the binary on `PATH` automatically, so
no `TESSERACT_CMD` override is needed in production at all.

## Local dev — Linux / macOS

```bash
# Debian/Ubuntu
sudo apt-get install tesseract-ocr

# macOS
brew install tesseract
```

Same as production: this puts `tesseract` on `PATH`, so no env var is
needed.

## Local dev — Windows

The official Windows build doesn't reliably add itself to an
already-open shell's `PATH` even after a successful install. Two steps:

1. Download and run the installer from the
   [UB-Mannheim Tesseract builds](https://github.com/UB-Mannheim/tesseract/wiki)
   (the community-maintained Windows build most guides point to), or the
   [official release](https://github.com/tesseract-ocr/tesseract/releases) —
   both install to `C:\Program Files\Tesseract-OCR\tesseract.exe` by
   default.
2. Set `TESSERACT_CMD` in `backend/.env` to that path, so `pytesseract`
   is told exactly where the binary is rather than relying on `PATH`:

   ```bash
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

Restart the backend dev server after setting it — `app/config.py` reads
it once at process startup.

## Verifying it worked

Confirm the binary itself is reachable first:

```bash
tesseract --version
```

Then upload a scanned PDF via the Documents page. Its extraction summary
shows `(N scanned page(s) read via OCR)` when any pages needed the OCR
fallback — the same detail is available on `GET /documents` and
`GET /documents/{id}` as `ocr_pages_used`. A document with none of its
pages needing OCR (i.e. every page had a real text layer) shows no such
note; that's the expected, unremarkable case for the vast majority of
uploads, since OCR only ever runs on pages that would otherwise have
extracted to nothing.

## What this doesn't do

OCR'd text is read via image recognition, not a text layer, so it's real
but lower-confidence than native extraction — misreads happen, especially
on low-quality scans, unusual fonts, or handwriting (Tesseract's default
model is tuned for printed text). It's flagged in the UI rather than
presented identically to a clean extraction for exactly that reason. Table
structure isn't reconstructed for OCR'd pages any more than it is for
native ones — see `document_intelligence.py`'s module docstring for that
existing, unrelated limitation.
