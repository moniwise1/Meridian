"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import FileOverviewCard from "@/components/FileOverviewCard";
import { readAskDraft, clearAskDraft } from "@/lib/askDraft";
import {
  listConnections,
  listDocuments,
  uploadDocument,
  askStream,
  type Connection,
  type DocumentSummary,
  type StepEvent,
  type ResultEvent,
} from "@/lib/api";
import AnalystWorkspace from "@/components/AnalystWorkspace";
import { useGlide } from "@/components/glide/useGlide";
import ClarificationPrompt from "@/components/ClarificationPrompt";
import ProgressTrace from "@/components/ProgressTrace";
import ResultView from "@/components/ResultView";

// The "Data source" picker offers both database connections and uploaded
// documents in one list — a document can now BE the thing being analysed,
// not only supplementary context attached to a database question (see
// app/agents/planner.py's document-only branch on the backend). Encoded
// as "conn:<id>" / "doc:<id>" in sourceValue and parsed back out on
// submit, so there's one selection model instead of two disconnected
// pieces of state that could disagree about what's actually selected.
type SourceSelection = { type: "connection"; id: string } | { type: "document"; id: string } | null;

function parseSourceValue(value: string): SourceSelection {
  if (value.startsWith("conn:")) return { type: "connection", id: value.slice(5) };
  if (value.startsWith("doc:")) return { type: "document", id: value.slice(4) };
  return null;
}

// One exchange in the chat thread - the question as the user actually
// typed it, the source it was asked against, and everything that came
// back for it. Kept as its own record (rather than re-deriving from a
// single shared `steps`/`result` pair) so earlier turns stay visible and
// frozen once a new question starts, the same reason any chat UI keeps
// every past message rather than only ever showing the latest one.
type Turn = {
  id: number;
  question: string;
  sourceLabel: string;
  steps: StepEvent[];
  result: ResultEvent | null;
  clarificationQuestion: string | null;
  clarificationAnswer: string | null;
};

export default function AskDashboard() {
  const uploadInput = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [continueThread, setContinueThread] = useState(true);
  const [loadingSources, setLoadingSources] = useState(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [sourceValue, setSourceValue] = useState("");
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [attachOpen, setAttachOpen] = useState(false);
  const [question, setQuestion] = useState(() => readAskDraft());
  useEffect(() => {
    clearAskDraft();
    const receive = (event: Event) => {
      const detail = (event as CustomEvent<{ question: string; platform: boolean }>).detail;
      if (!detail.platform) { setQuestion(detail.question); clearAskDraft(); }
    };
    window.addEventListener("meridian:ask-draft", receive);
    return () => window.removeEventListener("meridian:ask-draft", receive);
  }, []);
  const [running, setRunning] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  // `running` is state, so two clicks landing in the same React batch both
  // read the pre-update value and both fire a request. A ref updates
  // synchronously, which is what actually makes the guard hold.
  const requestRunning = useRef(false);
  // The selected-source pill glides between sources, including across a
  // wrapped second row, rather than one chip switching off as another
  // switches on (components/glide/useGlide.ts).
  const { containerRef: sourceRowRef, indicatorRef: sourceIndicatorRef } = useGlide<HTMLDivElement>(sourceValue);
  const threadEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    Promise.allSettled([listConnections(), listDocuments()]).then(([dbResult, fileResult]) => {
      if (!live) return;
      const dbs = dbResult.status === "fulfilled" ? dbResult.value : [];
      const files = fileResult.status === "fulfilled" ? fileResult.value : [];
      setConnections(dbs); setDocuments(files);
      const requestedFile = new URLSearchParams(window.location.search).get("document");
      const availableRequestedFile = files.find(file => file.id === requestedFile);
      setSourceValue(prev => prev || (availableRequestedFile ? `doc:${availableRequestedFile.id}` : dbs[0] ? `conn:${dbs[0].id}` : files[0] ? `doc:${files[0].id}` : ""));
      const errors = [dbResult.status === "rejected" ? "Databases: " + dbResult.reason.message : "",
        fileResult.status === "rejected" ? "Files: " + fileResult.reason.message : ""].filter(Boolean);
      setLoadError(errors.join(" · ") || (requestedFile && !availableRequestedFile ? "The requested file is unavailable in this workspace." : "")); setLoadingSources(false);
    });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const source = parseSourceValue(sourceValue);
  // Selecting a document AS the source is a distinct, single-document
  // mode — the separate "attach a supplementary document" popover (for a
  // database-backed question) is hidden in that case rather than letting
  // the two overlap confusingly.
  const documentIsSource = source?.type === "document";

  const activeTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const pendingClarification = !!activeTurn && !!activeTurn.clarificationQuestion && !activeTurn.result;
  const inputLocked = running || uploading || pendingClarification;

  function toggleDoc(id: string) {
    if (inputLocked || conversationId) return;
    setSelectedDocIds((prev) => (prev.includes(id) ? prev.filter((d) => d !== id) : prev.length < (documentIsSource ? 9 : 10) ? [...prev, id] : prev));
  }

  function currentSourceLabel(): string {
    if (!source) return "";
    if (source.type === "connection") return connections.find((c) => c.id === source.id)?.name ?? "Database";
    const filename = documents.find((d) => d.id === source.id)?.filename ?? "Document";
    return selectedDocIds.length ? `${filename} + ${selectedDocIds.length} supporting file(s)` : filename;
  }

  // turnId is set only when resuming a turn already in the thread (a
  // clarification answer/skip) - omitted for a brand new question, which
  // appends a fresh turn instead.
  async function runAsk(
    questionText: string,
    opts: { followUp: boolean; skipClarification: boolean; turnId?: number },
  ) {
    if (!source || requestRunning.current || uploading) return;
    requestRunning.current = true;
    const abortController = new AbortController();
    controller.current = abortController;
    setRunning(true);

    const id = opts.turnId ?? Date.now();
    if (opts.turnId === undefined) {
      setTurns((prev) => [...prev, {
        id, question: questionText, sourceLabel: currentSourceLabel(),
        steps: [], result: null, clarificationQuestion: null, clarificationAnswer: null,
      }]);
    }
    function patch(fn: (t: Turn) => Turn) {
      setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));
    }

    // Resuming a turn after a clarification: clear the question that was
    // asked, so the prompt disappears the moment the retry starts rather
    // than sitting there until the first event arrives.
    patch((t) => ({ ...t, clarificationQuestion: null }));
    try {
      await askStream(
        {
          connection_id: source.type === "connection" ? source.id : null,
          question: questionText,
          conversation_id: opts.followUp ? conversationId : null,
          // Always sent, including on a follow-up. A document-only
          // conversation is now bound to its documents server-side (see
          // planner.py's document_ids check), so dropping them on a
          // follow-up would make the thread fail to match its own
          // conversation instead of continuing it.
          document_ids: documentIsSource ? [source.id, ...selectedDocIds.filter(id => id !== source.id)] : selectedDocIds,
          skip_clarification: opts.skipClarification,
        },
        (evt) => {
          if (evt.type === "step") patch((t) => ({ ...t, steps: [...t.steps, evt] }));
          else if (evt.type === "clarification") {
            // Pauses here rather than producing a result - the analysis
            // never ran, nothing was persisted, so there's no partial
            // result to show alongside this.
            patch((t) => ({ ...t, clarificationQuestion: evt.question }));
          } else {
            patch((t) => ({ ...t, result: evt, clarificationQuestion: null }));
            setConversationId(evt.conversation_id);
          }
        },
        abortController.signal,
      );
    } catch (e) {
      patch((t) => ({
        ...t,
        steps: [...t.steps, { type: "step", step: "error", status: "error", detail: abortController.signal.aborted ? "Response stopped. An analysis already in progress may still finish." : (e as Error).message }],
      }));
    } finally {
      controller.current = null;
      requestRunning.current = false;
      setRunning(false);
    }
  }

  function askText(text: string, followUp: boolean) {
    if (!text.trim() || !source || inputLocked) return;
    runAsk(text, { followUp, skipClarification: false });
  }

  function handleAsk() {
    if (!question.trim() || inputLocked || !source) return;
    const text = question;
    setQuestion("");
    askText(text, !!conversationId && continueThread);
  }

  // Folds the clarifying question and the user's answer into one
  // self-contained question text, then re-asks with skip_clarification:
  // true - the same "combine into one question" idea context_resolver.py
  // already uses for follow-ups, just done here on the client rather than
  // needing the backend to remember any in-progress state. Reads the
  // original question straight off the turn itself (not ambient `question`
  // state, which is already cleared/reused for whatever the user types
  // next) so this stays correct even if they start typing a new message
  // before answering.
  function answerClarification(turn: Turn, answer: string) {
    if (!turn.clarificationQuestion) return;
    setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, clarificationAnswer: answer } : t)));
    const combined = `${turn.question}\n\n(Clarifying question: "${turn.clarificationQuestion}" — Answer: "${answer}")`;
    // Stays in the thread it was asked in. Before conversations were bound
    // to a source this had to start fresh; now that a clarification can
    // land mid-conversation, forcing followUp:false would silently fork a
    // second thread out of one question.
    runAsk(combined, { followUp: !!conversationId, skipClarification: true, turnId: turn.id });
  }

  function skipClarification(turn: Turn) {
    setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, clarificationAnswer: "Skipped — best guess" } : t)));
    runAsk(turn.question, { followUp: !!conversationId, skipClarification: true, turnId: turn.id });
  }

  function startNewConversation() {
    setConversationId(null);
    setContinueThread(true);
    setTurns([]);
    setQuestion("");
    setSelectedDocIds([]);
    setAttachOpen(false);
  }

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length || inputLocked) return;
    setUploading(true); setLoadError("");
    const uploaded: DocumentSummary[] = [];
    const errors: string[] = [];
    try {
      for (const file of files.slice(0, 5)) {
        try { uploaded.push(await uploadDocument(file)); }
        catch (error) { errors.push(`${file.name}: ${(error as Error).message}`); }
      }
      if (files.length > 5) errors.push("Choose up to five files per upload.");
      if (uploaded.length) {
        startNewConversation();
        setDocuments(previous => [...uploaded, ...previous]);
        setSourceValue(`doc:${uploaded[0].id}`);
        setSelectedDocIds(uploaded.slice(1).map(file => file.id));
      }
      setLoadError(errors.join(" · "));
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-8 py-8 sm:py-12">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-medium text-ink tracking-tight">What do you want to understand?</h1>
          <p className="text-[13.5px] text-ink-soft mt-1.5">
            Explore operations, customers, sales, inventory, research or any other subject in your data.
            Upload files or choose a connected database, then ask in your own words.
          </p>
        </div>
        {conversationId && (
          <button
            onClick={startNewConversation}
            disabled={running}
            className="shrink-0 text-[12.5px] text-teal hover:text-teal-deep transition-colors whitespace-nowrap disabled:opacity-40"
          >
            New conversation
          </button>
        )}
      </div>

      {turns.length === 0 && sourceValue && <div className="grid sm:grid-cols-3 gap-2 mb-6">
        {(documentIsSource ? ["Summarise the main findings and data limitations", "Which patterns or exceptions stand out?", "What should I verify before using these findings?"] : ["What data is available and what can we learn from it?", "Show the main trends and unusual changes", "Compare performance across the relevant categories"]).map(text => <button key={text} disabled={inputLocked} onClick={() => setQuestion(text)} className="text-left text-xs border border-line rounded-lg p-3 text-ink-soft hover:border-teal disabled:opacity-40">{text}</button>)}
      </div>}
      {loadingSources && <p role="status" className="text-sm text-ink-soft mb-4">Loading your authorized sources…</p>}
      {loadError && <div className="mb-6 text-[13px] text-red">{loadError}</div>}
      {connections.length === 0 && documents.length === 0 && !loadError && !loadingSources && (
        <div className="mb-6 p-3 border border-line rounded-[4px] text-[13px] text-ink-soft">
          No data sources connected and no documents uploaded yet. Go to{" "}
          <Link href="/connections" className="text-teal hover:text-teal-deep transition-colors">
            Data sources
          </Link>{" "}
          to connect a database, or{" "}
          <Link href="/documents" className="text-teal hover:text-teal-deep transition-colors">
            Documents
          </Link>{" "}
          to upload spreadsheets, documents, text or JSON exports to analyse directly.
        </div>
      )}

      {sourceValue && (
        // Remounted per source (key) - notes, saved conversations and
        // upload findings are all scoped to one source on the backend, so
        // switching sources must not briefly show the previous one's.
        <AnalystWorkspace
          key={sourceValue}
          sourceKey={sourceValue}
          disabled={inputLocked}
          revision={turns.filter((t) => t.result).length}
          onResume={(c) => {
            setConversationId(c.id);
            setSelectedDocIds(c.document_ids.filter(id => !documentIsSource || id !== source?.id));
            setQuestion("");
            setTurns(
              c.turns.map((t, i) => ({
                id: i,
                question: t.question,
                sourceLabel: currentSourceLabel(),
                steps: [],
                result: t.result,
                clarificationQuestion: null,
                clarificationAnswer: null,
              })),
            );
          }}
        />
      )}

      {/* ---------- Thread ---------- */}
      {turns.length > 0 && (
        <div className="flex flex-col gap-8 mb-6">
          {turns.map((turn) => {
            const nextQuestion =
              turn.result?.analysis?.follow_ups[0]?.question ??
              (turn.result && !("error" in turn.result.insight) ? turn.result.insight.next_question : null);
            const showSteps = turn.steps.length > 0 && (!turn.result || turn.steps.some((s) => s.status === "error"));
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                {/* User message */}
                <div className="self-end max-w-[85%]">
                  <div className="bg-teal-deep text-white text-[13.5px] rounded-[10px] rounded-br-[3px] px-4 py-2.5 whitespace-pre-wrap">
                    {turn.question}
                  </div>
                  <div className="text-[11px] text-ink-soft mt-1 text-right">{turn.sourceLabel}</div>
                </div>

                {/* Assistant content */}
                <div className="flex items-start gap-2.5">
                  <span className="shrink-0 mt-0.5 w-6 h-6 rounded-full bg-teal-deep text-white text-[11px] font-medium flex items-center justify-center">
                    M
                  </span>
                  <div className="flex-1 min-w-0 flex flex-col gap-3">
                    {showSteps && <ProgressTrace steps={turn.steps} />}
                    {turn.clarificationQuestion && !turn.result && (
                      <ClarificationPrompt
                        question={turn.clarificationQuestion}
                        busy={running}
                        onAnswer={(answer) => answerClarification(turn, answer)}
                        onSkip={() => skipClarification(turn)}
                      />
                    )}
                    {turn.clarificationAnswer && (
                      <div className="text-[12px] text-ink-soft italic">You answered: “{turn.clarificationAnswer}”</div>
                    )}
                    {turn.result && <ResultView result={turn.result} />}
                    {nextQuestion && (
                      <button
                        onClick={() => askText(nextQuestion, !!conversationId)}
                        disabled={inputLocked}
                        className="self-start text-[12.5px] px-3 py-1.5 rounded-full border border-teal text-teal hover:bg-teal hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {nextQuestion} →
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={threadEndRef} />
        </div>
      )}

      {conversationId && <label className="flex items-center gap-2 text-xs text-ink-soft mb-3"><input type="checkbox" checked={continueThread} disabled={inputLocked} onChange={e => setContinueThread(e.target.checked)} />Continue this conversation&apos;s context. Uncheck for an independent question.</label>}
      {running && <button onClick={() => controller.current?.abort()} className="text-sm text-teal mb-3">Stop response</button>}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <input ref={uploadInput} type="file" multiple accept=".pdf,.docx,.pptx,.xlsx,.csv,.tsv,.json,.txt,.md" className="sr-only" aria-label="Upload files to analyse" onChange={handleUpload} disabled={inputLocked} />
        <button type="button" disabled={inputLocked} onClick={() => uploadInput.current?.click()} className="text-xs border border-line rounded-md px-3 py-2 text-teal disabled:opacity-40">{uploading ? "Uploading files…" : "Upload files"}</button>
        <Link href="/connections" className="text-xs text-teal">Connect a database</Link>
        <span className="text-xs text-ink-soft">Excel, CSV, TSV, JSON, PDF, Word, PowerPoint, text and Markdown</span>
      </div>
      {/* ---------- Composer ---------- */}
      <div className="sticky bottom-4 bg-panel border border-line rounded-[8px] shadow-sm p-4">
        <div ref={sourceRowRef} className="relative flex items-center gap-2 mb-3 flex-wrap">
          <span
            ref={sourceIndicatorRef}
            aria-hidden
            className="pointer-events-none absolute left-0 top-0 z-0 opacity-0 rounded-full bg-teal-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_3px_10px_rgba(18,63,61,0.25)] transition-[transform,width,height,opacity] duration-[420ms] ease-glide motion-reduce:transition-none"
          />
          <span className="text-[11.5px] text-ink-soft shrink-0">Source:</span>
          {connections.map((c) => (
            <button
              key={c.id}
              type="button"
              // A conversation belongs to one source server-side, so
              // switching source has to start a new thread - continuing the
              // old one against a different source is rejected.
              onClick={() => {
                startNewConversation();
                setSourceValue(`conn:${c.id}`);
              }}
              disabled={inputLocked}
              data-glide-key={`conn:${c.id}`}
              className={`relative z-10 text-[12px] px-2.5 py-1 rounded-full border transition-colors duration-200 disabled:opacity-60 disabled:cursor-not-allowed ${
                sourceValue === `conn:${c.id}`
                  ? "text-white border-transparent [transition-delay:90ms]"
                  : "border-line text-ink-soft hover:border-teal hover:text-teal"
              }`}
            >
              {c.name}
            </button>
          ))}
          {documents.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => {
                startNewConversation();
                setSourceValue(`doc:${d.id}`);
              }}
              disabled={inputLocked}
              data-glide-key={`doc:${d.id}`}
              className={`relative z-10 text-[12px] px-2.5 py-1 rounded-full border transition-colors duration-200 disabled:opacity-60 disabled:cursor-not-allowed ${
                sourceValue === `doc:${d.id}`
                  ? "text-white border-transparent [transition-delay:90ms]"
                  : "border-line text-ink-soft hover:border-teal hover:text-teal"
              }`}
            >
              {d.filename}
            </button>
          ))}
          {connections.length === 0 && documents.length === 0 && (
            <span className="text-[12px] text-ink-soft">No data sources or documents available</span>
          )}
        </div>

        {documentIsSource && source && !conversationId && <FileOverviewCard
          documentId={source.id} filename={documents.find(file => file.id === source.id)?.filename ?? "Selected file"}
          onQuestion={setQuestion} disabled={inputLocked} />}

        {documentIsSource && (
          <div className="text-[11.5px] text-ink-soft mb-2">
            Analysing the selected file{selectedDocIds.length ? ` and ${selectedDocIds.length} supporting file(s)` : ""}. Database access is not required.
          </div>
        )}

        <div className="flex items-end gap-2">
          {!conversationId && documents.some(d => !documentIsSource || d.id !== source?.id) && (
            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => setAttachOpen((v) => !v)}
                disabled={inputLocked}
                title="Attach a document for this question to reference"
                className={`w-9 h-9 rounded-full border flex items-center justify-center text-[13px] transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                  selectedDocIds.length > 0
                    ? "border-teal-deep text-teal-deep"
                    : "border-line text-ink-soft hover:border-teal hover:text-teal"
                }`}
              >
                📎{selectedDocIds.length > 0 && <span className="ml-0.5">{selectedDocIds.length}</span>}
              </button>
              {attachOpen && (
                <div className="absolute bottom-11 left-0 w-64 bg-panel border border-line rounded-[6px] shadow-sm p-3 z-10">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-[11.5px] text-ink-soft">Attach documents (optional)</div>
                    <Link href="/documents" className="text-[11px] text-teal hover:text-teal-deep transition-colors">
                      Manage
                    </Link>
                  </div>
                  <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
                    {documents.filter(d => !documentIsSource || d.id !== source?.id).map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => toggleDoc(d.id)}
                        className={`text-left text-[12px] px-2 py-1.5 rounded-[3px] transition-colors ${
                          selectedDocIds.includes(d.id) ? "bg-teal-deep text-white" : "text-ink-soft hover:bg-paper"
                        }`}
                      >
                        {d.filename}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <textarea
            aria-label="Question for Ask Meridian"
            maxLength={8000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              // isComposing: mid-IME-composition Enter commits the
              // candidate text, it does not mean "send".
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                handleAsk();
              }
            }}
            disabled={inputLocked}
            placeholder={
              conversationId
                ? "Ask a follow-up — e.g. what about last month specifically?"
                : "e.g. Why did South-East revenue fall last quarter?"
            }
            rows={1}
            className="flex-1 text-[14px] border border-line rounded-[8px] px-3 py-2 bg-panel text-ink placeholder:text-ink-soft/70 resize-none focus:outline-none focus:ring-1 focus:ring-teal disabled:opacity-60 max-h-32"
          />
          <button
            onClick={handleAsk}
            disabled={inputLocked || !question.trim() || !source}
            className="shrink-0 w-9 h-9 rounded-full bg-teal-deep text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-teal transition-colors flex items-center justify-center"
            title={running ? "Analysing…" : "Send"}
          >
            {running ? "…" : "↑"}
          </button>
        </div>
        <div className="text-[10.5px] text-ink-soft mt-1.5">Enter to send · Shift+Enter for a new line</div>
      </div>
    </div>
  );
}
