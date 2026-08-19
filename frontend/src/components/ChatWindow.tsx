import { FormEvent, useState } from "react";
import type { ChatMessage } from "../types";
import { ApiError, sendChatMessage } from "../api/client";
import { MessageBubble } from "./MessageBubble";
import { LoadingIndicator } from "./LoadingIndicator";

export function ChatWindow({
  getToken,
  demoUserId,
}: {
  getToken: () => Promise<string>;
  demoUserId?: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [useLangGraph, setUseLangGraph] = useState(false);

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
      const response = await sendChatMessage(
        question,
        nextMessages,
        getToken,
        demoUserId,
        useLangGraph
      );
      setMessages([
        ...nextMessages,
        { role: "assistant", content: response.answer, citations: response.citations },
      ]);
    } catch (err) {
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
      <div className="pipeline-toggle">
        <label>
          <input
            type="checkbox"
            checked={useLangGraph}
            onChange={(e) => setUseLangGraph(e.target.checked)}
          />
          Use LangGraph pipeline (query rewriting + retrieval evaluation)
        </label>
      </div>
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
