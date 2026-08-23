import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, Citation } from "../types";
import { SourcesPill } from "./SourcesPill";
import { ReasoningSteps } from "./ReasoningSteps";

function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-0.5">
      <span className="h-1.5 w-1.5 animate-[typing-blink_1.2s_infinite] rounded-full bg-muted-foreground" />
      <span className="h-1.5 w-1.5 animate-[typing-blink_1.2s_infinite_0.2s] rounded-full bg-muted-foreground" />
      <span className="h-1.5 w-1.5 animate-[typing-blink_1.2s_infinite_0.4s] rounded-full bg-muted-foreground" />
    </div>
  );
}

export function MessageBubble({
  message,
  onOpenSources,
}: {
  message: ChatMessage;
  onOpenSources: (citations: Citation[]) => void;
}) {
  const isUser = message.role === "user";
  const hasReasoning = !isUser && (message.reasoningSteps?.length ?? 0) > 0;
  const waitingForFirstContent = message.isStreaming && !hasReasoning && !message.content;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={
          message.isError
            ? "max-w-[80%] rounded-2xl bg-destructive/10 px-4 py-3 text-destructive"
            : isUser
              ? "max-w-[80%] rounded-2xl bg-primary px-4 py-3 text-primary-foreground"
              : "max-w-full text-foreground"
        }
      >
        {hasReasoning && !message.isError && (
          <ReasoningSteps steps={message.reasoningSteps ?? []} live={message.isStreaming} />
        )}
        {waitingForFirstContent ? (
          <TypingDots />
        ) : isUser || message.isError ? (
          <p className="m-0 whitespace-pre-wrap leading-relaxed">
            {message.content}
            {message.isStreaming && !message.isError && (
              <span className="ml-0.5 inline-block h-4 w-[2px] animate-[typing-blink_1.2s_infinite] bg-current align-middle" />
            )}
          </p>
        ) : (
          <div className="md-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            {message.isStreaming && (
              <span className="ml-0.5 inline-block h-4 w-[2px] animate-[typing-blink_1.2s_infinite] bg-current align-middle" />
            )}
          </div>
        )}
        {message.citations && message.citations.length > 0 && (
          <SourcesPill citations={message.citations} onOpen={onOpenSources} />
        )}
      </div>
    </div>
  );
}
