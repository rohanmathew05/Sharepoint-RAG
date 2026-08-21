import { FormEvent, useState } from "react";
import { ArrowUp } from "lucide-react";
import type { ChatMessage, Citation } from "../types";
import { ApiError, SessionExpiredError, sendChatMessage } from "../api/client";
import { MessageBubble } from "./MessageBubble";
import { LoadingIndicator } from "./LoadingIndicator";
import { SourcesPanel } from "./SourcesPanel";

export function ChatWindow({
  getToken,
  onSessionExpired,
}: {
  getToken: () => Promise<string>;
  // Called instead of rendering an error bubble when the backend reports
  // the session is genuinely gone (not something a silent retry can
  // fix) — lets the parent show a proper "sign in again" prompt instead
  // of burying it in the conversation.
  onSessionExpired?: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [openSourcesFor, setOpenSourcesFor] = useState<Citation[] | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || isLoading) return;

    const userMessage: ChatMessage = { role: "user", content: question };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setIsLoading(true);

    try {
      const response = await sendChatMessage(question, nextMessages, getToken);
      setMessages([
        ...nextMessages,
        { role: "assistant", content: response.answer, citations: response.citations },
      ]);
    } catch (err) {
      if (err instanceof SessionExpiredError && onSessionExpired) {
        onSessionExpired();
        // Drop the pending user message rather than leaving it sitting
        // in history unanswered — it never actually reached the model.
        setMessages(messages);
        return;
      }
      const detail = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      setMessages([
        ...nextMessages,
        { role: "assistant", content: detail, isError: true },
      ]);
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
          {isLoading && <LoadingIndicator />}
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
