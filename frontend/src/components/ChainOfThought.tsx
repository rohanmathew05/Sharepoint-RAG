import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ChainOfThoughtStep {
  label: string;
  detail?: string;
  icon?: React.ReactNode;
}

function Step({ step, isLast }: { step: ChainOfThoughtStep; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(step.detail);

  return (
    <div className="relative flex gap-3 pb-4 last:pb-0">
      {!isLast && (
        <span className="absolute left-[9px] top-5 h-[calc(100%-0.5rem)] w-px bg-border" />
      )}
      <span className="relative z-10 mt-1.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center text-muted-foreground">
        {step.icon ?? <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />}
      </span>
      <div className="min-w-0 flex-1">
        <button
          type="button"
          disabled={!expandable}
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "flex items-center gap-1.5 text-sm text-muted-foreground",
            expandable && "cursor-pointer hover:text-foreground"
          )}
        >
          <span>{step.label}</span>
          {expandable && (
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
          )}
        </button>
        {open && step.detail && (
          <p className="mt-1.5 mb-0 text-sm leading-relaxed text-foreground">{step.detail}</p>
        )}
      </div>
    </div>
  );
}

export function ChainOfThought({ steps }: { steps: ChainOfThoughtStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="flex flex-col">
      {steps.map((step, i) => (
        <Step key={i} step={step} isLast={i === steps.length - 1} />
      ))}
    </div>
  );
}
