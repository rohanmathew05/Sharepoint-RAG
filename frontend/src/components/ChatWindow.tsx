import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";
import type { ChatMessage, Citation } from "../types";
import { ApiError, SessionExpiredError, getConversation, streamChatMessage } from "../api/client";
import { MessageBubble } from "./MessageBubble";
import { SourcesPanel } from "./SourcesPanel";

export function ChatWindow({
  getToken,
  onSessionExpired,
  conversationId,
  onConversationCreated,
  onConversationUpdated,
}: {
  getToken: () => Promise<string>;
  // Called instead of rendering an error bubble when the backend reports
  // the session is genuinely gone (not something a silent retry can
  // fix) — lets the parent show a proper "sign in again" prompt instead
  // of burying it in the conversation.
  onSessionExpired?: () => void;
  // null = a brand-new, not-yet-persisted chat (messages start empty and
  // the backend lazily creates a conversation on first send). Non-null
  // switches to loading and displaying that conversation's messages.
  conversationId: string | null;
  // Fired once, when a new chat's first message causes the backend to
  // create a conversation — lets the parent adopt the id so the sidebar
  // and subsequent messages in this session reuse it.
  onConversationCreated: (id: string) => void;
  // Fired after an exchange completes, so the parent can refresh the
  // sidebar (e.g. to pick up the auto-derived title / updated timestamp).
  onConversationUpdated?: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [openSourcesFor, setOpenSourcesFor] = useState<Citation[] | null>(null);
  // When this component's own submit flow creates a conversation
  // mid-stream (conversationId was null), the resulting conversationId
  // prop change would otherwise re-trigger the fetch effect below and
  // clobber the in-progress streaming message with what's persisted so
  // far (just the user's message — the assistant reply isn't saved until
  // the stream finishes). Tracking the id we just created locally lets
  // the effect recognize "this change came from us" and skip the fetch.
  const justCreatedIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (conversationId === null) {
      setMessages([]);
      return;
    }
    if (conversationId === justCreatedIdRef.current) {
      justCreatedIdRef.current = null;
      return;
    }
    let cancelled = false;
    getConversation(conversationId, getToken)
      .then((detail) => {
        if (!cancelled) setMessages(detail.messages);
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || isLoading) return;

    const userMessage: ChatMessage = { role: "user", content: question };
    const nextMessages = [...messages, userMessage];
    // The assistant's reply streams into this same message object as
    // events arrive — reasoning steps append to reasoningSteps, answer
    // tokens append to content — rather than only appearing once
    // everything is done.
    const assistantIndex = nextMessages.length;
    setMessages([...nextMessages, { role: "assistant", content: "", reasoningSteps: [], isStreaming: true }]);
    setInput("");
    setIsLoading(true);

    function updateAssistant(update: (m: ChatMessage) => ChatMessage) {
      setMessages((prev) => {
        const next = [...prev];
        next[assistantIndex] = update(next[assistantIndex]);
        return next;
      });
    }

    try {
      await streamChatMessage(question, nextMessages, conversationId, getToken, (event) => {
        if (event.type === "conversation") {
          // Only fires for a brand-new chat (conversationId was null) —
          // adopt the id the backend just assigned so the parent's state
          // (and the sidebar) picks it up.
          if (conversationId === null) {
            justCreatedIdRef.current = event.id;
            onConversationCreated(event.id);
          }
        } else if (event.type === "step") {
          updateAssistant((m) => ({
            ...m,
            reasoningSteps: [...(m.reasoningSteps ?? []), event.step],
          }));
        } else if (event.type === "token") {
          updateAssistant((m) => ({ ...m, content: m.content + event.text }));
        } else if (event.type === "done") {
          updateAssistant((m) => ({
            ...m,
            content: event.answer,
            citations: event.citations,
            isStreaming: false,
          }));
          onConversationUpdated?.();
        } else if (event.type === "error") {
          if (event.error_code === "obo_token_expired" && onSessionExpired) {
            onSessionExpired();
            // Drop the pending exchange rather than leaving a broken
            // streaming bubble in history — it never actually finished.
            setMessages(messages);
          } else {
            updateAssistant((m) => ({
              ...m,
              content: event.detail,
              isError: true,
              isStreaming: false,
            }));
          }
        }
      });
    } catch (err) {
      if (err instanceof SessionExpiredError && onSessionExpired) {
        onSessionExpired();
        setMessages(messages);
      } else {
        const detail = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
        updateAssistant((m) => ({ ...m, content: detail, isError: true, isStreaming: false }));
      }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col">
      <div className="flex-1 overflow-y-auto px-6 py-8">
        {messages.length === 0 && (
          <div className="py-16 text-center text-sm text-muted-foreground">
            Ask a question about company documents you have access to, e.g.
            <br />
            <em>"What PPE is required when working in a confined space?"</em>
          </div>
        )}
        <div className="flex flex-col gap-4">
          {messages.map((m, i) => (
            <MessageBubble key={i} message={m} onOpenSources={setOpenSourcesFor} />
          ))}
        </div>
      </div>
      <form
        className="flex items-end gap-2 border-t border-border bg-surface px-6 py-4"
        onSubmit={handleSubmit}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about company documents..."
          disabled={isLoading}
          className="flex-1 rounded-xl border border-input bg-background px-4 py-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/30 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
        >
          <ArrowUp className="h-5 w-5" />
        </button>
      </form>
      <SourcesPanel citations={openSourcesFor} onClose={() => setOpenSourcesFor(null)} />
    </div>
  );
}
