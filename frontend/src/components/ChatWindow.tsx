import { FormEvent, useState } from "react";
import type { ChatMessage } from "../types";
import { ApiError, SessionExpiredError, sendChatMessage } from "../api/client";
import { MessageBubble } from "./MessageBubble";
import { LoadingIndicator } from "./LoadingIndicator";

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
    <div className="chat-window">
      <div className="chat-history">
        {messages.length === 0 && (
          <div className="empty-state">
            Ask a question about company documents you have access to, e.g.
            <em> "What PPE is required when working in a confined space?"</em>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {isLoading && <LoadingIndicator />}
      </div>
      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about company documents..."
          disabled={isLoading}
        />
        <button type="submit" disabled={isLoading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
