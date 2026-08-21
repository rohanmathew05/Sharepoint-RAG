import { useState } from "react";
import { ChevronDown, Search, ListChecks, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { ChainOfThought, type ChainOfThoughtStep } from "./ChainOfThought";

// Built purely from what backend/models/chat.py's ChatResponse already
// returns today (retrieval_attempts + citation count) — an honest summary
// of which pipeline stages ran (see backend/services/langgraph_pipeline.py),
// not the model's actual token-level reasoning. Showing the real search
// queries tried and per-attempt relevance verdicts would need the backend
// to start returning that trace (RAGState already tracks it internally as
// `previous_queries` / `is_relevant`, it just isn't on ChatResponse yet).
function buildSteps(retrievalAttempts: number, citationCount: number): ChainOfThoughtStep[] {
  const steps: ChainOfThoughtStep[] = [
    { label: "Understanding the question", icon: <Sparkles className="h-3.5 w-3.5" /> },
  ];

  if (retrievalAttempts > 0) {
    steps.push({
      label: "Searching SharePoint",
      icon: <Search className="h-3.5 w-3.5" />,
      detail:
        retrievalAttempts === 1
          ? "Ran a search against the documents you have access to."
          : `Ran ${retrievalAttempts} search attempts, rewriting the query each time the first result wasn't relevant.`,
    });
    steps.push({
      label: "Reviewing results",
      icon: <ListChecks className="h-3.5 w-3.5" />,
      detail:
        citationCount > 0
          ? `Found ${citationCount} relevant document${citationCount === 1 ? "" : "s"} to answer from.`
          : "No relevant documents were found in what you have access to.",
    });
  }

  steps.push({ label: "Composing the answer", icon: <Sparkles className="h-3.5 w-3.5" /> });
  return steps;
}

export function ReasoningSteps({
  retrievalAttempts,
  citationCount,
}: {
  retrievalAttempts: number;
  citationCount: number;
}) {
  const [open, setOpen] = useState(false);
  const steps = buildSteps(retrievalAttempts, citationCount);

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <span>Reasoning ({steps.length} steps)</span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-3 rounded-lg border border-border bg-surface px-3 py-3">
          <ChainOfThought steps={steps} />
        </div>
      )}
    </div>
  );
}
