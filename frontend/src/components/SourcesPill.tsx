import { FileText } from "lucide-react";
import type { Citation } from "../types";
import { Badge } from "./ui/badge";

export function SourcesPill({
  citations,
  onOpen,
}: {
  citations: Citation[];
  onOpen: (citations: Citation[]) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(citations)}
      className="mt-3 inline-flex rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <Badge className="cursor-pointer px-3.5 py-2 text-sm hover:bg-primary hover:text-primary-foreground">
        <FileText className="h-4 w-4" />
        {citations.length} {citations.length === 1 ? "Source" : "Sources"}
      </Badge>
    </button>
  );
}
