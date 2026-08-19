import type { ChatMessage } from "../types";
import { SourceCard } from "./SourceCard";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`message-row ${isUser ? "message-row-user" : "message-row-assistant"}`}>
      <div className={`message-bubble ${message.isError ? "message-bubble-error" : ""}`}>
        <p className="message-text">{message.content}</p>
        {message.citations && message.citations.length > 0 && (
          <div className="sources">
            <div className="sources-label">Sources</div>
            <div className="sources-list">
              {message.citations.map((c) => (
                <SourceCard key={c.document_id} citation={c} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
