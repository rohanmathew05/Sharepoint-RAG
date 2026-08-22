import type { Citation } from "../types";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "./ui/sheet";
import { SourceCard } from "./SourceCard";

export function SourcesPanel({
  citations,
  onClose,
}: {
  citations: Citation[] | null;
  onClose: () => void;
}) {
  const open = citations !== null;

  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{citations?.length ?? 0} Sources</SheetTitle>
        </SheetHeader>
        <div className="flex flex-1 flex-col gap-2 overflow-y-auto px-5 py-4">
          {citations?.map((c) => (
            <SourceCard key={c.document_id} citation={c} />
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
