export interface ChainOfThoughtStep {
  label: string;
  detail?: string;
  icon?: React.ReactNode;
}

function Step({ step, isLast }: { step: ChainOfThoughtStep; isLast: boolean }) {
  return (
    <div className="relative flex gap-3 pb-4 last:pb-0">
      {!isLast && (
        <span className="absolute left-[7px] top-5 h-[calc(100%-0.5rem)] w-px bg-border" />
      )}
      <span className="relative z-10 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
        {step.icon ?? <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />}
      </span>
      <div className="min-w-0 flex-1">
        <span className="text-sm text-muted-foreground">{step.label}</span>
        {step.detail && (
          <p className="mb-0 mt-1 text-sm leading-relaxed text-foreground">{step.detail}</p>
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
