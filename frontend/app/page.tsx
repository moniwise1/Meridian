"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listConnections,
  listDocuments,
  askStream,
  type Connection,
  type DocumentSummary,
  type StepEvent,
  type ResultEvent,
} from "@/lib/api";
import ProgressTrace from "@/components/ProgressTrace";
import ResultView from "@/components/ResultView";

export default function AskPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [result, setResult] = useState<ResultEvent | null>(null);
  const [running, setRunning] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);

  useEffect(() => {
    listConnections()
      .then((rows) => {
        setConnections(rows);
        if (rows.length > 0) setConnectionId(rows[0].id);
      })
      .catch((e) => setLoadError(e.message));
    listDocuments()
      .then(setDocuments)
      .catch(() => {}); // no document_retrieval capability, or none uploaded yet — fine either way
  }, []);

  function toggleDoc(id: string) {
    setSelectedDocIds((prev) => (prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]));
  }

  async function handleAsk(followUp = false) {
    if (!question.trim() || !connectionId) return;
    setRunning(true);
    setSteps([]);
    setResult(null);
    try {
      await askStream(
        {
          connection_id: connectionId,
          question,
          conversation_id: followUp ? conversationId : null,
          // Attaching documents forces a fresh (non-follow-up) question
          // server-side too, but keep the UI consistent with that rule.
          document_ids: followUp ? [] : selectedDocIds,
        },
        (evt) => {
          if (evt.type === "step") setSteps((prev) => [...prev, evt]);
          else {
            setResult(evt);
            setConversationId(evt.conversation_id);
          }
        },
      );
    } catch (e) {
      setSteps((prev) => [...prev, { type: "step", step: "error", status: "error", detail: (e as Error).message }]);
    } finally {
      setRunning(false);
    }
  }

  function startNewConversation() {
    setConversationId(null);
    setResult(null);
    setSteps([]);
    setQuestion("");
    setSelectedDocIds([]);
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-medium text-ink tracking-tight">What do you want to understand?</h1>
          <p className="text-[13.5px] text-ink-soft mt-1.5">
            Ask a business question. The agent will find the relevant authorized data, analyse it,
            check for anomalies, and explain the answer with evidence.
          </p>
        </div>
        {conversationId && (
          <button
            onClick={startNewConversation}
            className="shrink-0 text-[12.5px] text-teal hover:text-teal-deep transition-colors whitespace-nowrap"
          >
            New conversation
          </button>
        )}
      </div>

      {loadError && <div className="mb-6 text-[13px] text-red">{loadError}</div>}
      {connections.length === 0 && !loadError && (
        <div className="mb-6 p-3 border border-line rounded-[4px] text-[13px] text-ink-soft">
          No data sources connected yet. Go to <span className="text-teal">Data sources</span> to connect one.
        </div>
      )}

      <div className="bg-panel border border-line rounded-[4px] p-4 mb-8">
        <div className="flex items-center gap-3 mb-3">
          <label className="text-[12.5px] text-ink-soft shrink-0">Data source</label>
          <select
            value={connectionId}
            onChange={(e) => setConnectionId(e.target.value)}
            className="text-[13px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink flex-1"
          >
            {connections.length === 0 && <option value="">No data sources connected</option>}
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.database})
              </option>
            ))}
          </select>
        </div>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleAsk(!!conversationId);
          }}
          placeholder={
            conversationId
              ? "Ask a follow-up — e.g. what about last month specifically?"
              : "e.g. Why did South-East revenue fall last quarter?"
          }
          rows={3}
          className="w-full text-[14px] border border-line rounded-[3px] px-3 py-2.5 bg-panel text-ink placeholder:text-ink-soft/70 resize-none focus:outline-none focus:ring-1 focus:ring-teal"
        />

        {!conversationId && documents.length > 0 && (
          <div className="mt-3 pt-3 border-t border-line">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[12px] text-ink-soft">
                Attach a document for this question to reference (optional):
              </div>
              <Link href="/documents" className="text-[11.5px] text-teal hover:text-teal-deep transition-colors">
                Manage documents
              </Link>
            </div>
            <div className="flex flex-wrap gap-2">
              {documents.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => toggleDoc(d.id)}
                  className={`text-[12px] px-2.5 py-1 rounded-[3px] border transition-colors ${
                    selectedDocIds.includes(d.id)
                      ? "bg-teal-deep text-white border-teal-deep"
                      : "border-line text-ink-soft hover:border-teal hover:text-teal"
                  }`}
                >
                  {d.filename}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end mt-3">
          <button
            onClick={() => handleAsk(!!conversationId)}
            disabled={running || !question.trim() || !connectionId}
            className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-teal transition-colors"
          >
            {running ? "Analysing…" : conversationId ? "Ask follow-up" : "Ask"}
          </button>
        </div>
      </div>

      {steps.length > 0 && (
        <div className="mb-8">
          <ProgressTrace steps={steps} />
        </div>
      )}

      {result && <ResultView result={result} />}
    </div>
  );
}
