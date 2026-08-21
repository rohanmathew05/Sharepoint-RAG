export function LoadingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-2xl bg-surface-alt px-4 py-3">
        <span className="h-1.5 w-1.5 animate-[typing-blink_1.2s_infinite] rounded-full bg-muted-foreground" />
        <span className="h-1.5 w-1.5 animate-[typing-blink_1.2s_infinite_0.2s] rounded-full bg-muted-foreground" />
        <span className="h-1.5 w-1.5 animate-[typing-blink_1.2s_infinite_0.4s] rounded-full bg-muted-foreground" />
      </div>
    </div>
  );
}
