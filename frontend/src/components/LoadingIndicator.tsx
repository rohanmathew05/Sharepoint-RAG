export function LoadingIndicator() {
  return (
    <div className="message-row message-row-assistant">
      <div className="message-bubble message-bubble-loading">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </div>
    </div>
  );
}
