"use client";

import { useEffect, useRef, useState } from "react";
import {
  listDocuments,
  uploadDocument,
  getDocument,
  deleteDocument,
  type DocumentSummary,
} from "@/lib/api";

const KIND_LABEL: Record<string, string> = {
  pdf: "PDF", docx: "Word document", xlsx: "Spreadsheet", pptx: "PowerPoint",
};

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState("");
  const [previewError, setPreviewError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  function refresh() {
    listDocuments()
      .then(setDocuments)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await uploadDocument(file);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handlePreview(id: string) {
    if (previewId === id) {
      setPreviewId(null);
      return;
    }
    setPreviewId(id);
    setPreviewText("");
    setPreviewError("");
    try {
      const doc = await getDocument(id);
      setPreviewText(doc.extracted_text);
    } catch (err) {
      setPreviewError((err as Error).message);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteDocument(id);
      if (previewId === id) setPreviewId(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Documents</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Upload a PDF, Word, PowerPoint, or Excel file to attach its content to a question on the Ask
        screen — the agent will reference it alongside the database analysis. Text and table content
        only (PowerPoint slide text, tables, and speaker notes). Scanned/image-only PDF pages are read
        via OCR automatically, up to 15 pages per document. Only the first 50,000 characters of a
        document are used.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="bg-panel border border-line rounded-[4px] p-4 mb-8">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.pptx,.xlsx"
          onChange={handleFileSelected}
          disabled={uploading}
          className="text-[13px] text-ink file:mr-3 file:text-[12.5px] file:px-3 file:py-1.5 file:rounded-[3px] file:border file:border-line file:bg-panel file:text-ink hover:file:border-teal hover:file:text-teal file:cursor-pointer disabled:opacity-40"
        />
        {uploading && <span className="ml-3 text-[12.5px] text-ink-soft">Uploading and extracting…</span>}
      </div>

      <div className="flex flex-col gap-3">
        {documents.map((d) => (
          <div key={d.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[13.5px] text-ink truncate">{d.filename}</div>
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  {KIND_LABEL[d.kind] ?? d.kind} · {d.char_count.toLocaleString()} chars extracted
                  {d.truncated ? " (truncated)" : ""}
                  {d.ocr_pages_used > 0
                    ? ` (${d.ocr_pages_used} scanned page${d.ocr_pages_used === 1 ? "" : "s"} read via OCR)`
                    : ""} · {new Date(d.created_at).toLocaleString()}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => handlePreview(d.id)}
                  className="text-[11.5px] text-teal hover:text-teal-deep transition-colors"
                >
                  {previewId === d.id ? "Hide" : "Preview"}
                </button>
                <button
                  onClick={() => handleDelete(d.id)}
                  className="text-[11.5px] text-red hover:opacity-70 transition-opacity"
                >
                  Delete
                </button>
              </div>
            </div>
            {previewId === d.id && (
              <div className="mt-3 pt-3 border-t border-line">
                {previewError && <div className="text-[12.5px] text-red">{previewError}</div>}
                {!previewError && (
                  <pre className="text-[12px] font-[family-name:var(--font-mono)] text-ink-soft whitespace-pre-wrap max-h-64 overflow-y-auto">
                    {previewText || "No text could be extracted from this file."}
                  </pre>
                )}
              </div>
            )}
          </div>
        ))}
        {documents.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">No documents uploaded yet.</div>
        )}
      </div>
    </div>
  );
}
