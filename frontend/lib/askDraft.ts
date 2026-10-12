import { loadSession } from "@/lib/auth";
import { loadPlatformSession } from "@/lib/platformAuth";
function draftKey(platform: boolean) {
  const staff = platform ? loadPlatformSession() : null;
  const user = platform ? null : loadSession();
  return platform ? `meridian:ask-draft:platform:${staff?.staffId ?? "none"}` : `meridian:ask-draft:${user?.tenantId ?? "none"}:${user?.userId ?? "none"}`;
}
export function readAskDraft(platform = false) {
  if (typeof window === "undefined") return "";
  try { return (sessionStorage.getItem(draftKey(platform)) ?? "").slice(0, platform ? 1000 : 8000); }
  catch { return ""; }
}
export function clearAskDraft(platform = false) {
  try { sessionStorage.removeItem(draftKey(platform)); } catch { /* Restricted browser storage does not prevent normal Ask use. */ }
}
export function saveAskDraft(question: string, platform = false) {
  const text = question.trim().slice(0, platform ? 1000 : 8000);
  sessionStorage.setItem(draftKey(platform), text);
  window.dispatchEvent(new CustomEvent("meridian:ask-draft", { detail: { question: text, platform } }));
}
