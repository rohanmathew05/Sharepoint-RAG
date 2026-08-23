import { useRef, useState } from "react";
import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ConversationSummary } from "../types";

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function ConversationTitle({
  conversation,
  onRename,
}: {
  conversation: ConversationSummary;
  onRename: (id: string, title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);

  function startEditing() {
    setDraft(conversation.title);
    setEditing(true);
    // Focus happens after the input mounts, on the next tick.
    requestAnimationFrame(() => inputRef.current?.select());
  }

  function commit() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed && trimmed !== conversation.title) onRename(conversation.id, trimmed);
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        onClick={(e) => e.stopPropagation()}
        autoFocus
        className="block w-full truncate rounded border border-input bg-background px-1 py-0 text-sm text-foreground outline-none focus:border-primary"
      />
    );
  }

  return (
    <span
      onDoubleClick={(e) => {
        e.stopPropagation();
        startEditing();
      }}
      className="block truncate"
      title="Double-click to rename"
    >
      {conversation.title || "New conversation"}
    </span>
  );
}

export function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
}: {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}) {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-surface">
      <div className="p-3">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-alt"
        >
          <Plus className="h-4 w-4" />
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-muted-foreground">
            No conversations yet.
          </p>
        )}
        <div className="flex flex-col gap-0.5">
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "group flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors",
                c.id === activeId
                  ? "bg-primary/10 text-foreground"
                  : "text-muted-foreground hover:bg-surface-alt hover:text-foreground"
              )}
            >
              <MessageSquare className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">
                <ConversationTitle conversation={c} onRename={onRename} />
                <span className="block truncate text-xs text-muted-foreground">
                  {relativeTime(c.updated_at)}
                </span>
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(c.id);
                }}
                aria-label="Delete conversation"
                className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
