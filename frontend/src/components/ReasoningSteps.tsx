import { useEffect, useRef, useState } from "react";
import { ChevronDown, Search, ListChecks, Sparkles, MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReasoningStep as ReasoningStepData } from "../types";
import { ChainOfThought, type ChainOfThoughtStep } from "./ChainOfThought";

// Maps backend/models/chat.py's ReasoningStep.kind (a real pipeline stage
// — see LangGraphRAGService's _step calls) to an icon. Unknown kinds
// still render, just with the default dot marker.
const KIND_ICONS: Record<string, React.ReactNode> = {
  understand: <Sparkles className="h-3.5 w-3.5" />,
  search: <Search className="h-3.5 w-3.5" />,
  evaluate: <ListChecks className="h-3.5 w-3.5" />,
  compose: <Sparkles className="h-3.5 w-3.5" />,
  skip: <MessageCircle className="h-3.5 w-3.5" />,
};

function toChainOfThoughtSteps(steps: ReasoningStepData[]): ChainOfThoughtStep[] {
  return steps.map((s) => ({
    label: s.label,
    detail: s.detail ?? undefined,
    icon: KIND_ICONS[s.kind],
  }));
}

export function ReasoningSteps({ steps, live }: { steps: ReasoningStepData[]; live?: boolean }) {
  // Defaults open while the reply is still streaming in, so the work is
  // visible as it happens rather than hidden behind an extra click —
  // collapsible afterwards the same as any other message.
  const [open, setOpen] = useState(Boolean(live));
  // Auto-collapse the instant streaming finishes (the live -> not-live
  // edge), rather than staying open forever once opened — a manual
  // toggle mid-stream still works right up to that transition.
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live) {
      setOpen(false);
    }
    wasLive.current = live;
  }, [live]);

  if (steps.length === 0) return null;

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <span>
          {live ? "Reasoning…" : `Reasoning (${steps.length} step${steps.length === 1 ? "" : "s"})`}
        </span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-3">
          <ChainOfThought steps={toChainOfThoughtSteps(steps)} />
        </div>
      )}
    </div>
  );
}
