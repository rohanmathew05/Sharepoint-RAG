import type { ChatMessage, Citation } from "../types";
import { SourcesPill } from "./SourcesPill";

export function MessageBubble({
  message,
  onOpenSources,
}: {
  message: ChatMessage;
  onOpenSources: (citations: Citation[]) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          message.isError
            ? "bg-destructive/10 text-destructive"
            : isUser
              ? "bg-primary text-primary-foreground"
              : "bg-surface-alt text-foreground"
        }`}
      >
        <p className="m-0 whitespace-pre-wrap leading-relaxed">{message.content}</p>
        {message.citations && message.citations.length > 0 && (
          <SourcesPill citations={message.citations} onOpen={onOpenSources} />
        )}
      </div>
    </div>
  );
}
